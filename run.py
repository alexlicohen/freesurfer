#!/usr/bin/env python3
import argparse
import os
import shutil
from glob import glob
from subprocess import Popen, PIPE
from shutil import rmtree
import subprocess

def run(command, env={}, ignore_errors=False):
    merged_env = os.environ
    merged_env.update(env)
    # DEBUG env triggers freesurfer to produce gigabytes of files
    merged_env.pop('DEBUG', None)
    process = Popen(command, stdout=PIPE, stderr=subprocess.STDOUT, shell=True, env=merged_env)
    while True:
        line = process.stdout.readline()
        line = str(line, 'utf-8')[:-1]
        print(line)
        if line == '' and process.poll() != None:
            break
    if process.returncode != 0 and not ignore_errors:
        raise Exception("Non zero return code: %d"%process.returncode)

__version__ = open('/version').read()

parser = argparse.ArgumentParser(description='FreeSurfer recon-all + custom template generation.')
parser.add_argument('bids_dir', help='The directory with the input dataset '
                    'formatted according to the BIDS standard.')
parser.add_argument('output_dir', help='The directory where the output files '
                    'should be stored. If you are running group level analysis '
                    'this folder should be prepopulated with the results of the'
                    'participant level analysis.')
parser.add_argument('analysis_level', help='Level of the analysis that will be performed. '
                    'Multiple participant level analyses can be run independently '
                    '(in parallel) using the same output_dir.',
                    choices=['participant', 'group'])
parser.add_argument('--participant_label', help='The label of the participant that should be analyzed. The label '
                   'corresponds to sub-<participant_label> from the BIDS spec '
                   '(so it does not include "sub-"). If this parameter is not '
                   'provided all subjects should be analyzed. Multiple '
                   'participants can be specified with a space separated list.',
                   nargs="+")
parser.add_argument('--n_cpus', help='Number of CPUs/cores available to use.',
                   default=1, type=int)
parser.add_argument('--stages', help='Autorecon stages to run.',
                    choices=["autorecon1", "autorecon2", "autorecon3", "autorecon-all"],
                    default=["autorecon-all"],
                    nargs="+")
parser.add_argument('--template_name', help='Name for the custom group level template generated for this dataset',
                    default="average")
parser.add_argument('--license_key', help='FreeSurfer license key - letters and numbers after "*" in the email you received after registration. To register (for free) visit https://surfer.nmr.mgh.harvard.edu/registration.html',
                    required=True)
parser.add_argument('--acquisition_label', help='If the dataset contains multiple T1 weighted images from different acquisitions which one should be used? Corresponds to "acq-<acquisition_label>"')
parser.add_argument('-v', '--version', action='version',
                    version='BIDS-App example version {}'.format(__version__))

args = parser.parse_args()

run("bids-validator " + args.bids_dir)

# check if study with session folders includes at least one subject with longitudinal t1w data
# if not, subject specific template and long stream are not run
longitudinal_study = False
subject_dirs = glob(os.path.join(args.bids_dir, "sub-*"))
if args.acquisition_label:
    acq_tpl = "*acq-%s*" % args.acquisition_label
else:
    acq_tpl = "*"

if glob(os.path.join(args.bids_dir, "sub-*", "ses-*")):
    subjects = [subject_dir.split("-")[-1] for subject_dir in subject_dirs]
    for subject_label in subjects:
        session_dirs = glob(os.path.join(args.bids_dir,"sub-%s"%subject_label,"ses-*"))
        sessions = [os.path.split(dr)[-1].split("-")[-1] for dr in session_dirs]
        n_valid_sessions = 0
        for session_label in sessions:
            if glob(os.path.join(args.bids_dir, "sub-%s"%subject_label,
                                                "ses-%s"%session_label,
                                                "anat",
                                                "%s_T1w.nii*"%acq_tpl)):
                n_valid_sessions += 1
        if n_valid_sessions > 1:
            longitudinal_study = True
            break


subjects_to_analyze = []
# only for a subset of subjects
if args.participant_label:
    subjects_to_analyze = args.participant_label
# for all subjects
else:
    subject_dirs = glob(os.path.join(args.bids_dir, "sub-*"))
    subjects_to_analyze = [subject_dir.split("-")[-1] for subject_dir in subject_dirs]

# workaround for https://mail.nmr.mgh.harvard.edu/pipermail//freesurfer/2016-July/046538.html
output_dir = os.path.abspath(args.output_dir)

# running participant level
if args.analysis_level == "participant":
    if not os.path.exists(os.path.join(output_dir, "fsaverage")):
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "fsaverage") + " " + os.path.join(output_dir, "fsaverage"),
            ignore_errors=True)
    if not os.path.exists(os.path.join(output_dir, "lh.EC_average")):
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "lh.EC_average") + " " + os.path.join(output_dir, "lh.EC_average"),
            ignore_errors=True)
    if not os.path.exists(os.path.join(output_dir, "rh.EC_average")):
        run("cp -rf " + os.path.join(os.environ["SUBJECTS_DIR"], "rh.EC_average") + " " + os.path.join(output_dir, "rh.EC_average"),
            ignore_errors=True)
    # find all T1s and skullstrip them
    for subject_label in subjects_to_analyze:

        session_dirs = glob(os.path.join(args.bids_dir,"sub-%s"%subject_label,"ses-*"))
        sessions = [os.path.split(dr)[-1].split("-")[-1] for dr in session_dirs]
        timepoints = []

        if len(sessions) > 0:
            for session_label in sessions:
                input_args = " ".join(["-i %s"%f for f in glob(os.path.join(args.bids_dir,
                                                                "sub-%s"%subject_label,
                                                                "ses-%s"%session_label,
                                                                "anat",
                                                                "%s_T1w.nii*"%acq_tpl))])
                T2s = glob(os.path.join(args.bids_dir, "sub-%s"%subject_label,
                                        "ses-%s"%session_label, "anat",
                                        "*_T2w.nii*"))
                if T2s:
                    input_args += " " + " ".join(["-T2 %s"%f for f in T2s])
                    input_args += " -T2pial"

                fsid = "sub-%s_ses-%s"%(subject_label, session_label)
                timepoints.append(fsid)
                cmd = "recon-all -subjid %s -sd %s %s -all -openmp %d"%(fsid,
                                                                        output_dir,
                                                                        input_args,
                                                                        args.n_cpus)
                print(cmd)
                if os.path.exists(os.path.join(output_dir, fsid)):
                    rmtree(os.path.join(output_dir, fsid))
                run(cmd)

            # creating a subject specific template
            if longitudinal_study:
                input_args = " ".join(["-tp %s"%tp for tp in timepoints])
                fsid = "sub-%s"%subject_label
                stages = " ".join(["-" + stage for stage in args.stages])
                cmd = "recon-all -base %s -sd %s %s %s -openmp %d"%(fsid,
                                                                    output_dir,
                                                                    input_args,
                                                                    stages,
                                                                    args.n_cpus)
                print(cmd)
                if os.path.exists(os.path.join(output_dir, fsid)):
                    rmtree(os.path.join(output_dir, fsid))
                run(cmd)

                for tp in timepoints:
                    # longitudinally process all timepoints
                    fsid = "sub-%s"%subject_label
                    stages = " ".join(["-" + stage for stage in args.stages])
                    cmd = "recon-all -long %s %s -sd %s %s -openmp %d"%(tp,
                                                                        fsid,
                                                                        output_dir,
                                                                        stages,
                                                                        args.n_cpus)
                    print(cmd)
                    if os.path.exists(os.path.join(output_dir, tp + ".long." + fsid)):
                        rmtree(os.path.join(output_dir, tp + ".long." + fsid))
                    run(cmd)

        else:
            # grab all T1s from all sessions
            input_args = " ".join(["-i %s"%f for f in glob(os.path.join(args.bids_dir,
                                                            "sub-%s"%subject_label,
                                                            "anat",
                                                            "%s_T1w.nii*"%acq_tpl))])
            T2s = glob(os.path.join(args.bids_dir, "sub-%s"%subject_label, "anat",
                                    "*_T2w.nii*"))
            if T2s:
                input_args += " " + " ".join(["-T2 %s"%f for f in T2s])
                input_args += " -T2pial"
            fsid = "sub-%s"%subject_label
            stages = " ".join(["-" + stage for stage in args.stages])
            cmd = "recon-all -subjid %s -sd %s %s %s -openmp %d"%(fsid,
                                                                  output_dir,
                                                                  input_args,
                                                                  stages,
                                                                  args.n_cpus)
            print(cmd)
            if os.path.exists(os.path.join(output_dir, fsid)):
                rmtree(os.path.join(output_dir, fsid))
            run(cmd)
elif args.analysis_level == "group":    	# running group level
    if len(subjects_to_analyze) > 1:
        # generate study specific template
        fsids = ["sub-%s"%s for s in subjects_to_analyze]
        cmd = "make_average_subject --no-symlink --out " + args.template_name + " --subjects " + " ".join(fsids)
        print(cmd)
        if os.path.exists(os.path.join(output_dir, args.template_name)):
            rmtree(os.path.join(output_dir, args.template_name))
        run(cmd, env={"SUBJECTS_DIR": output_dir})
        for subject_label in subjects_to_analyze:
            for hemi in ["lh", "rh"]:
                tif_file = os.path.join(output_dir, args.template_name, hemi+".reg.template.tif")
                fsid = "sub-%s"%subject_label
                sphere_file = os.path.join(output_dir, fsid, "surf", hemi+".sphere")
                reg_file = os.path.join(output_dir, fsid, "surf", hemi+".sphere.reg." + args.template_name)
                cmd = "mris_register -curv %s %s %s"%(sphere_file, tif_file, reg_file)
                run(cmd, env={"SUBJECTS_DIR": output_dir})
    else:
        print("Only one subject included in the analysis. Skipping group level")
