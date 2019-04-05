#!/bin/sh -l

#
#-----------------------------------------------------------------------
#
# Check arguments.
#
#-----------------------------------------------------------------------
#
if [ "$#" -ne 8 ]; then

  printf "\

Script \"$0\":  Incorrect number of arguments specified.
Usage:

  $0  BASEDIR  predef_domain  grid_gen_method  CCPP  CCPP_phys_suite  CDATE  fcst_len_hrs  quilting

where the arguments are defined as follows:

  BASEDIR:
  The directory in which the FV3SAR workflow repository was cloned.

  predef_domain:
  The predefined domain to use.

  grid_gen_method:
  The horizontal grid generation method to use.

  CCPP
  Whether or not to run a CCPP-enabled verson of the FV3SAR.

  CCPP_phys_suite
  The physics suite to use.

  CDATE
  The starting date (and hour) of the forecast.

  fsct_len_hrs
  The length of the forecast, in hours.

  quilting
  Whether or not to use the write-component to write output files.

These are described in more detail in the documentation of the FV3SAR 
workflow.

Exiting script with nonzero exit code.\n"

  exit 1

fi
#
#-----------------------------------------------------------------------
#
# Set directories.
#
#-----------------------------------------------------------------------
#
BASEDIR=${1:-}
USHDIR="$BASEDIR/fv3sar_workflow/ush"
#
#-----------------------------------------------------------------------
#
# Source useful functions (sort of like a library).
#
#-----------------------------------------------------------------------
#
. $USHDIR/source_funcs.sh
#
#-----------------------------------------------------------------------
#
# Set forecast parameters.
#
#-----------------------------------------------------------------------
#
predef_domain=${2:-}
grid_gen_method=${3:-}
CCPP=${4:-}
CCPP_phys_suite=${5:-}
CDATE=${6:-}
fcst_len_hrs=${7:-}
quilting="${8:-}"

dot_quilting=".${quilting}."

print_info_msg "\
User-specified forecast parameters:

  predef_domain = \"${predef_domain}\"
  grid_gen_method = \"${grid_gen_method}\"
  CCPP = \"${CCPP}\"
  CCPP_phys_suite = \"${CCPP_phys_suite}\"
  CDATE = \"${CDATE}\"
  fcst_len_hrs = \"${fcst_len_hrs}\"
  quilting = \"${quilting}\""
#
#-----------------------------------------------------------------------
#
# Construct new variables based on input arguments.
#
#-----------------------------------------------------------------------
#
#BASEDIR="/scratch3/BMC/det/Gerard.Ketefian/UFS_CAM"
#USHDIR="$BASEDIR/fv3sar_workflow/ush"
CONFIG_FN="config.sh"
CONFIG_FP="${USHDIR}/${CONFIG_FN}"
REGR_TEST_BASEDIR="$BASEDIR/regr_tests"

TEST_NAME="${predef_domain}_${grid_gen_method}_CCPP${CCPP}_${CCPP_phys_suite}phys_${CDATE}_FCST${fcst_len_hrs}hrs_QUILT$quilting"
#TEST_DATE=$( date "+%Y%m%d-%H_%M" )
TEST_DATE=$( date "+%Y%m%d" )
#RUNDIR_BASE="${REGR_TEST_BASEDIR}/tested_on_${TEST_DATE}"
#RUNDIR_BASE="$BASEDIR/run_dirs/test_date_${TEST_DATE}"
#RUN_SUBDIR="$TEST_NAME"
RUNDIR_BASE="$BASEDIR/run_dirs"
RUN_SUBDIR="test_date_${TEST_DATE}/$TEST_NAME"
TMPDIR="$BASEDIR/work_dirs"

print_info_msg "\
Variables constructed from user-specified forecast parameters:

  BASEDIR = \"${BASEDIR}\"
  USHDIR = \"${USHDIR}\"
  CONFIG_FN = \"${CONFIG_FN}\"
  CONFIG_FP = \"${CONFIG_FP}\"
  REGR_TEST_BASEDIR = \"${REGR_TEST_BASEDIR}\"

  TEST_NAME = \"${TEST_NAME}\"
  TEST_DATE = \"${TEST_DATE}\"
  RUNDIR_BASE = \"${RUNDIR_BASE}\"
  RUN_SUBDIR = \"${RUN_SUBDIR}\""
#
#-----------------------------------------------------------------------
#
# Use a heredoc to construct the configuration file for the forecast.  
# Note that whatever is not specified in this file is obtained from 
# config_defaults.sh.
#
#-----------------------------------------------------------------------
#
{ cat << EOM > $CONFIG_FP
#
#-----------------------------------------------------------------------
#
# This is the local workflow configuration file.  It is not tracked by 
# the git repository.
#
#-----------------------------------------------------------------------
#
MACHINE="THEIA"
ACCOUNT="gsd-fv3"
QUEUE_DEFAULT="batch"
QUEUE_HPSS="service"
QUEUE_RUN_FV3SAR="batch"
#
BASEDIR="$BASEDIR"
TMPDIR="$TMPDIR"
UPPDIR="/scratch3/BMC/det/beck/FV3-CAM/EMC_post/sorc/ncep_post.fd"
RUNDIR_BASE="$RUNDIR_BASE"
RUN_SUBDIR="$RUN_SUBDIR"
#
CDATE="$CDATE"
fcst_len_hrs="$fcst_len_hrs"
BC_update_intvl_hrs="6"
#
run_title=""
#
predef_domain="$predef_domain"
#
grid_gen_method="$grid_gen_method"
#
preexisting_dir_method="delete"
quilting="$dot_quilting"
#
CCPP="$CCPP"
CCPP_phys_suite="$CCPP_phys_suite"
EOM
}
#
#-----------------------------------------------------------------------
#
# Generate workflow XML for the specified experiment configuration and
# save the output in a log file for debugging.  Then move the log file
# to the run directory.
#
#-----------------------------------------------------------------------
#
cd_vrfy $USHDIR
LOG_GEN_WFLOW_FP="$USHDIR/log.generate_FV3SAR_wflow"
./generate_FV3SAR_wflow.sh > "$LOG_GEN_WFLOW_FP" 2>&1
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
  print_err_msg_exit "\
Workflow generation script returned with a nonzero exit status.
Check the log file located at:
  LOG_GEN_WFLOW_FP = \"$LOG_GEN_WFLOW_FP\""
fi

RUNDIR="$RUNDIR_BASE/$RUN_SUBDIR"
mv_vrfy log.generate_FV3SAR_wflow $RUNDIR
#
#-----------------------------------------------------------------------
#
# Create a script in the run directory that can be used to (re)launch 
# the workflow and report on its status.  This script saves its output 
# to a log file (in the run directory) for debugging purposes and to al-
# low the user to check on the status of the workflow.
#
#-----------------------------------------------------------------------
#
cd_vrfy $RUNDIR

ROCOTO_EXEC_DIR="/apps/rocoto/1.2.4/bin"
XML_BASENAME="FV3SAR_wflow"
RELAUNCH_SCR="relaunch_wflow.sh"

{ cat << EOM > ${RELAUNCH_SCR}
#!/bin/sh -l

module load rocoto
cd $RUNDIR
{
${ROCOTO_EXEC_DIR}/rocotorun -w ${XML_BASENAME}.xml -d ${XML_BASENAME}.db -v 10 ;
echo ;
${ROCOTO_EXEC_DIR}/rocotostat -w ${XML_BASENAME}.xml -d ${XML_BASENAME}.db -v 10 ; 
} >> log.rocotostat 2>&1
EOM
}
#
# Make the relaunch script executable.
#
chmod u+x $RELAUNCH_SCR
#
#-----------------------------------------------------------------------
#
# Add a line to the user's cron table to call the (re)launch script at
# some frequency (e.g. every 5 minutes).
#
#-----------------------------------------------------------------------
#
CRONTAB_ORIG="$(pwd)/crontab.orig"
print_info_msg "\
Copying contents of user cron table to backup file:
  CRONTAB_ORIG = \"$CRONTAB_ORIG\""
crontab -l > $CRONTAB_ORIG

crontab_line="*/5 * * * * cd $RUNDIR && ./$RELAUNCH_SCR" 
#echo "$crontab_line"
#
# Below, we will use "grep" to determine whether the above crontab line
# is already present in the cron table.  For that purpose, we need to 
# escape the asterisks in the crontab line with backslashes.  Do this
# next.
#
crontab_line_esc_astr=$( echo "$crontab_line" | sed -r -e "s![*]!\\\\*!g" )
grep_output=$( crontab -l | grep "$crontab_line_esc_astr" )
exit_status=$?
#echo "grep_output = $grep_output"
#echo "exit_status = $exit_status"

if [ "$exit_status" -eq 0 ]; then

  print_info_msg "\
The following line already exists in the cron table and thus will not be
added:
  crontab_line = \"$crontab_line\""
  
else

  print_info_msg "\
Adding the following line to the cron table in order to automatically
resubmit FV3SAR workflow:
  crontab_line = \"$crontab_line\""

  (crontab -l 2>/dev/null; echo "$crontab_line") | crontab -

fi


