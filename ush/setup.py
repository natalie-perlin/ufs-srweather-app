#!/usr/bin/env python3

import copy
import json
import os
import sys
import datetime
import traceback
import logging
from textwrap import dedent

import yaml
from uwtools.api.config import get_yaml_config
from pprint import pprint

from python_utils import (
    cd_vrfy,
    date_to_str,
    mkdir_vrfy,
    rm_vrfy,
    check_var_valid_value,
    lowercase,
    uppercase,
    dict_find,
    list_to_str,
    check_for_preexist_dir_file,
    flatten_dict,
    check_structure_dict,
    update_dict,
    import_vars,
    get_env_var,
    load_config_file,
    cfg_to_shell_str,
    cfg_to_yaml_str,
    load_ini_config,
    get_ini_value,
    str_to_list,
    extend_yaml,
    has_tag_with_value,
    load_xml_file,
)

from set_cycle_and_obs_timeinfo import \
     set_cycle_dates, set_fcst_output_times_and_obs_days_all_cycles, \
     set_rocoto_cycledefs_for_obs_days, \
     check_temporal_consistency_cumul_fields, \
     get_obs_retrieve_times_by_day
from set_predef_grid_params import set_predef_grid_params
from set_gridparams_ESGgrid import set_gridparams_ESGgrid
from set_gridparams_GFDLgrid import set_gridparams_GFDLgrid
from link_fix import link_fix

def load_config_for_setup(ushdir, default_config, user_config):
    """Updates a Python dictionary in place with experiment configuration settings from the
    default, machine, and user configuration files.

    Args:
      ushdir             (str): Path to the ``ush`` directory for the SRW App
      default_config     (str): Path to ``config_defaults.yaml``
      user_config        (str): Path to the user-provided config YAML (usually named
                                ``config.yaml``)

    Returns:
        cfg_d            (dict): Experiment configuration dictionary based on default,
                                 machine, and user config files
        do_vx            (bool): Flag specifying whether workflow will run vx tasks

    Raises:
        FileNotFoundError: If the user-provided configuration file or the machine file does not
                           exist.
        Exception: If (1) the user-provided configuration file cannot be loaded or (2) it contains
                   invalid sections/keys or (3) it does not contain mandatory information or (4)
                   an invalid datetime format is used.
    """

    # Load the default config.
    logging.debug(f"Loading config defaults file {default_config}")
    cfg_d = load_config_file(default_config)
    logging.debug(f"Read in the following values from config defaults file:\n")
    logging.debug(cfg_d)

    # Load the user config file, then ensure all user-specified
    # variables correspond to a default value.
    if not os.path.exists(user_config):
        raise FileNotFoundError(
            f"""
            User config file not found:
            user_config = {user_config}
            """
        )

    try:
        cfg_u = load_config_file(user_config)
        logging.debug(f"Read in the following values from YAML config file {user_config}:\n")
        logging.debug(cfg_u)
    except:
        errmsg = dedent(
            f"""\n
            Could not load YAML config file:  {user_config}
            Reference the above traceback for more information.
            """
        )
        raise Exception(errmsg)

    # Make sure the keys in user config match those in the default
    # config.
    invalid = check_structure_dict(cfg_u, cfg_d)

    # Task and metatask entries can be added arbitrarily under the
    # rocoto section. Remove those from invalid if they exist
    for key in invalid.copy().keys():
        if key.split("_", maxsplit=1)[0] in ["task", "metatask"]:
            invalid.pop(key)
            logging.info(f"Found and allowing key {key}")

    if invalid:
        errmsg = f"Invalid key(s) specified in {user_config}:\n"
        for entry in invalid:
            errmsg = errmsg + f"{entry} = {invalid[entry]}\n"
        errmsg = errmsg + f"\nCheck {default_config} for allowed user-specified variables\n"
        raise Exception(errmsg)

    # Mandatory variables *must* be set in the user's config; the default value is invalid
    mandatory = ["user.MACHINE"]
    for val in mandatory:
        sect, key = val.split(".")
        user_setting = cfg_u.get(sect, {}).get(key)
        if user_setting is None:
            raise Exception(
                f"""Mandatory variable "{val}" not found in
            user config file {user_config}"""
            )

    # Load the machine config file
    machine = uppercase(cfg_u.get("user").get("MACHINE"))
    cfg_u["user"]["MACHINE"] = uppercase(machine)

    machine_file = os.path.join(ushdir, "machine", f"{lowercase(machine)}.yaml")

    if not os.path.exists(machine_file):
        raise FileNotFoundError(
            dedent(
                f"""
            The machine file {machine_file} does not exist.
            Check that you have specified the correct machine
            ({machine}) in your config file {user_config}"""
            )
        )
    logging.debug(f"Loading machine defaults file {machine_file}")
    machine_cfg = load_config_file(machine_file)

    # Load the fixed files configuration
    cfg_f = load_config_file(
        os.path.join(ushdir, os.pardir, "parm", "fixed_files_mapping.yaml")
    )

    # Load the constants file
    cfg_c = load_config_file(os.path.join(ushdir, "constants.yaml"))


    # Load the rocoto workflow default file
    cfg_wflow = load_config_file(os.path.join(ushdir, os.pardir, "parm",
        "wflow", "default_workflow.yaml"))

    # Takes care of removing any potential "null" entries, i.e.,
    # unsetting a default value from an anchored default_task
    update_dict(cfg_wflow, cfg_wflow)


    # Take any user-specified taskgroups entry here.
    taskgroups = cfg_u.get('rocoto', {}).get('tasks', {}).get('taskgroups')
    if taskgroups:
        cfg_wflow['rocoto']['tasks']['taskgroups'] = taskgroups

    # Save string specifying final workflow taskgroups for use later on.
    taskgroups = cfg_wflow['rocoto']['tasks']['taskgroups']

    # Extend yaml here on just the rocoto section to include the
    # appropriate groups of tasks
    extend_yaml(cfg_wflow)

    # Put the entries expanded under taskgroups in tasks
    rocoto_tasks = cfg_wflow["rocoto"]["tasks"]
    cfg_wflow["rocoto"]["tasks"] = yaml.load(rocoto_tasks.pop("taskgroups"),Loader=yaml.SafeLoader)

    # Update wflow config from user one more time to make sure any of
    # the "null" settings are removed, i.e., tasks turned off.
    update_dict(cfg_u.get('rocoto', {}), cfg_wflow["rocoto"])

    def _add_jobname(tasks):
        """ Adds the jobname entry for all the tasks in the workflow """

        if not isinstance(tasks, dict):
            return
        for task, task_settings in tasks.items():
            task_type = task.split("_", maxsplit=1)[0]
            if task_type == "task":
                # Use the provided attribute if it is present, otherwise use
                # the name in the key
                tasks[task]["jobname"] = \
                    task_settings.get("attrs", {}).get("name") or \
                    task.split("_", maxsplit=1)[1]
            elif task_type == "metatask":
                _add_jobname(task_settings)


    # Add jobname entry to each remaining task
    _add_jobname(cfg_wflow["rocoto"]["tasks"])

    # Update default config with the constants, the machine config, and
    # then the user_config
    # Recall: update_dict updates the second dictionary with the first,
    # and so, we update the default config settings in place with all
    # the others.

    # Constants
    update_dict(cfg_c, cfg_d)

    # Default workflow settings
    update_dict(cfg_wflow, cfg_d)

    # Machine settings
    update_dict(machine_cfg, cfg_d)

    # Fixed files
    update_dict(cfg_f, cfg_d)

    # User settings (take precedence over all others)
    update_dict(cfg_u, cfg_d)

    # Update the cfg_d against itself now, to remove any "null"
    # stranglers.
    update_dict(cfg_d, cfg_d)

    # Set "Home" directory, the top-level ufs-srweather-app directory
    homedir = os.path.abspath(os.path.dirname(__file__) + os.sep + os.pardir)
    cfg_d["user"]["HOMEdir"] = homedir

    # Special logic if EXPT_BASEDIR is a relative path; see config_defaults.yaml for explanation
    expt_basedir = cfg_d["workflow"]["EXPT_BASEDIR"]
    if (not expt_basedir) or (expt_basedir[0] != "/"):
        expt_basedir = os.path.join(homedir, "..", "expt_dirs", expt_basedir)
    try:
        expt_basedir = os.path.realpath(expt_basedir)
    except:
        pass
    cfg_d["workflow"]["EXPT_BASEDIR"] = os.path.abspath(expt_basedir)
    #
    # -----------------------------------------------------------------------
    #
    # If the workflow includes at least one verification task, ensure that
    # the configuration parameters associated with cumulative fields (e.g.
    # APCP) in the verification section of the experiment dicitonary are
    # temporally consistent, e.g. that accumulation intervals are less than
    # or equal to the forecast length.  Update the verification section of
    # the dictionary to remove inconsistencies.
    #
    # -----------------------------------------------------------------------
    #
    # List containing the names of all workflow config files for vx (i.e.
    # whether or not they're included in the workflow).
    vx_taskgroup_fns = ['verify_pre.yaml', 'verify_det.yaml', 'verify_ens.yaml']
    # Flag that specifies whether the workflow will be running any vx tasks.
    do_vx = any([fn for fn in vx_taskgroup_fns if fn in taskgroups])

    # Initialize variable containing the vx configuration.  This may be 
    # modified within the if-statement below.
    vx_config = cfg_d["verification"]

    if do_vx:
        workflow_config = cfg_d["workflow"]

        date_first_cycl = workflow_config.get("DATE_FIRST_CYCL")
        date_last_cycl = workflow_config.get("DATE_LAST_CYCL")
        incr_cycl_freq = int(workflow_config.get("INCR_CYCL_FREQ"))
        fcst_len_hrs = workflow_config.get("FCST_LEN_HRS")
        vx_fcst_output_intvl_hrs = vx_config.get("VX_FCST_OUTPUT_INTVL_HRS")

        # Convert various times and time intervals from integers or strings to
        # datetime or timedelta objects.
        date_first_cycl_dt = datetime.datetime.strptime(date_first_cycl, "%Y%m%d%H")
        date_last_cycl_dt = datetime.datetime.strptime(date_last_cycl, "%Y%m%d%H")
        cycl_intvl_dt = datetime.timedelta(hours=incr_cycl_freq)
        fcst_len_dt = datetime.timedelta(hours=fcst_len_hrs)
        vx_fcst_output_intvl_dt = datetime.timedelta(hours=vx_fcst_output_intvl_hrs)

        # Generate a list containing the starting times of the cycles.
        cycle_start_times \
        = set_cycle_dates(date_first_cycl_dt, date_last_cycl_dt, cycl_intvl_dt,
                          return_type='datetime')

        # Call function that runs the consistency checks on the vx parameters.
        vx_config, fcst_obs_matched_times_all_cycles_cumul \
        = check_temporal_consistency_cumul_fields(
          vx_config, cycle_start_times, fcst_len_dt, vx_fcst_output_intvl_dt)


    cfg_d['verification'] = vx_config
    extend_yaml(cfg_d)

    # Do any conversions of data types
    for sect, settings in cfg_d.items():
        for k, v in settings.items():
            if not (v is None or v == ""):
                cfg_d[sect][k] = str_to_list(v)

    # Mandatory variables *must* be set in the user's config or the machine file; the default value is invalid
    mandatory = [
        "NCORES_PER_NODE",
        "FIXgsm",
        "FIXaer",
        "FIXlut",
        "FIXorg",
        "FIXsfc",
    ]
    flat_cfg = flatten_dict(cfg_d)
    for val in mandatory:
        if not flat_cfg.get(val):
            raise Exception(
                dedent(
                    f"""
                    Mandatory variable "{val}" not found in:
                    user config file {user_config}
                                  OR
                    machine file {machine_file}
                    """
                )
            )

    # Check that input dates are in a date format
    dates = ["DATE_FIRST_CYCL", "DATE_LAST_CYCL"]
    for val in dates:
        if not isinstance(cfg_d["workflow"][val], datetime.date):
            raise Exception(
                dedent(
                    f"""
                        Date variable {val}={cfg_d['workflow'][val]} is not in a valid date format.

                        For examples of valid formats, see the Users' Guide.
                        """
                )
            )

    return cfg_d, do_vx


def set_srw_paths(ushdir, expt_config):

    """
    Generates a dictionary of directories that describe the SRW App
    structure, i.e., where the SRW App is installed and the paths to
    external repositories managed via the ``manage_externals`` tool.

    Other paths for the SRW App are set as defaults in ``config_defaults.yaml``.

    Args:
        ushdir      (str) : Path to the system location of the ``ush`` directory under the
                            SRW App clone
        expt_config (dict): Contains the configuration settings for the user-defined experiment

    Returns:
        Dictionary of configuration settings and system paths as keys/values

    Raises:
        KeyError: If the external repository required is not listed in the externals
                  configuration file (e.g., ``Externals.cfg``)
        FileNotFoundError: If the ``ufs-weather-model`` code containing the FV3 source code has
                           not been cloned properly
    """

    # HOMEdir is the location of the SRW clone, one directory above ush/
    homedir = expt_config.get("user", {}).get("HOMEdir")

    # Read Externals.cfg
    mng_extrns_cfg_fn = os.path.join(homedir, "Externals.cfg")
    try:
        mng_extrns_cfg_fn = os.readlink(mng_extrns_cfg_fn)
    except:
        pass
    cfg = load_ini_config(mng_extrns_cfg_fn)

    # Get the base directory of the FV3 forecast model code.
    external_name = expt_config.get("workflow", {}).get("FCST_MODEL")
    property_name = "local_path"

    try:
        ufs_wthr_mdl_dir = get_ini_value(cfg, external_name, property_name)
    except KeyError:
        errmsg = dedent(
            f"""
            Externals configuration file {mng_extrns_cfg_fn}
            does not contain '{external_name}'."""
        )
        raise Exception(errmsg) from None

    # Check that the model code has been downloaded
    ufs_wthr_mdl_dir = os.path.join(homedir, ufs_wthr_mdl_dir)
    if not os.path.exists(ufs_wthr_mdl_dir):
        raise FileNotFoundError(
            dedent(
                f"""
                The base directory in which the FV3 source code should be located
                (UFS_WTHR_MDL_DIR) does not exist:
                  UFS_WTHR_MDL_DIR = '{ufs_wthr_mdl_dir}'
                Please clone the external repository containing the code in this directory,
                build the executable, and then rerun the workflow."""
            )
        )

    return dict(
        USHdir=ushdir,
        UFS_WTHR_MDL_DIR=ufs_wthr_mdl_dir,
    )


def setup(USHdir, user_config_fn="config.yaml", debug: bool = False):
    """Validates user-provided configuration settings and derives
    a secondary set of parameters needed to configure a Rocoto-based SRW App
    workflow. The secondary parameters are derived from a set of required
    parameters defined in ``config_defaults.yaml``, a user-provided
    configuration file (e.g., ``config.yaml``), or a YAML machine file.

    A set of global variable definitions is saved to the experiment
    directory as a bash configure file that is sourced by scripts at run
    time.

    Args:
        USHdir          (str): The full path of the ``ush/`` directory where this script
                               (``setup.py``) is located
        user_config_fn  (str): The name of a user-provided configuration YAML (usually
                               ``config.yaml``)
        debug          (bool): Enable extra output for debugging

    Returns:
        None

    Raises:
        ValueError: If checked configuration values are invalid (e.g., forecast length,
                    ``EXPTDIR`` path)
        FileExistsError: If ``EXPTDIR`` already exists, and ``PREEXISTING_DIR_METHOD`` is not
                         set to a compatible handling method
        FileNotFoundError: If the path to a particular file does not exist or if the file itself
                           does not exist at the expected path
        TypeError: If ``USE_CUSTOM_POST_CONFIG_FILE`` or ``USE_CRTM`` are set to true but no
                   corresponding custom configuration file or CRTM fix file directory is set
        KeyError: If an invalid value is provided (i.e., for ``GRID_GEN_METHOD``)
    """

    logger = logging.getLogger(__name__)

    # print message
    logger.info(
        f"""
        ========================================================================
        Starting function setup() in \"{os.path.basename(__file__)}\"...
        ========================================================================"""
    )

    # Create a dictionary of config options from defaults, machine, and
    # user config files.
    default_config_fp = os.path.join(USHdir, "config_defaults.yaml")
    user_config_fp = os.path.join(USHdir, user_config_fn)
    expt_config, do_vx = load_config_for_setup(USHdir, default_config_fp, user_config_fp)

    # Load build settings as a dictionary; will be used later to make sure the build is consistent with the user settings
    build_config_fp = os.path.join(expt_config["user"].get("EXECdir"), "build_settings.yaml")
    build_config = load_config_file(build_config_fp)
    logger.debug(f"Read build configuration from {build_config_fp}\n{build_config}")

    # Fail if build machine and config machine are inconsistent
    if build_config["Machine"].upper() != expt_config["user"]["MACHINE"]:
        logger.critical("ERROR: Machine in build settings file != machine specified in config file")
        logger.critical(f"build machine: {build_config['Machine']}")
        logger.critical(f"config machine: {expt_config['user']['MACHINE']}")
        raise ValueError("Check config settings for correct value for 'machine'")

    # Set up some paths relative to the SRW clone
    expt_config["user"].update(set_srw_paths(USHdir, expt_config))

    #
    # -----------------------------------------------------------------------
    #
    # Validate the experiment configuration starting with the workflow,
    # then in rough order of the tasks in the workflow
    #
    # -----------------------------------------------------------------------
    #

    # Workflow
    workflow_config = expt_config["workflow"]

    workflow_id = workflow_config["WORKFLOW_ID"]
    logger.info(f"""WORKFLOW ID = {workflow_id}""")

    debug = workflow_config.get("DEBUG")
    if debug:
        logger.info(
            """
            Setting VERBOSE to \"TRUE\" because DEBUG has been set to \"TRUE\"..."""
        )
        workflow_config["VERBOSE"] = True

    verbose = workflow_config["VERBOSE"]

    # The forecast length (in integer hours) cannot contain more than 3 characters.
    # Thus, its maximum value is 999.
    fcst_len_hrs_max = 999
    fcst_len_hrs = workflow_config.get("FCST_LEN_HRS")
    if fcst_len_hrs > fcst_len_hrs_max:
        raise ValueError(
            f"""
            Forecast length is greater than maximum allowed length:
              FCST_LEN_HRS = {fcst_len_hrs}
              fcst_len_hrs_max = {fcst_len_hrs_max}"""
        )


    #
    # -----------------------------------------------------------------------
    #
    # Set the full path to the experiment directory.  Then check if it already
    # exists and if so, deal with it as specified by PREEXISTING_DIR_METHOD.
    #
    # -----------------------------------------------------------------------
    #

    expt_subdir = workflow_config.get("EXPT_SUBDIR", "")
    exptdir = workflow_config.get("EXPTDIR")

    # Update some paths that include EXPTDIR and EXPT_BASEDIR
    extend_yaml(expt_config)
    preexisting_dir_method = workflow_config.get("PREEXISTING_DIR_METHOD", "")
    try:
        check_for_preexist_dir_file(exptdir, preexisting_dir_method)
    except ValueError:
        logger.exception(
            f"""
            Check that the following values are valid:
            EXPTDIR {exptdir}
            PREEXISTING_DIR_METHOD {preexisting_dir_method}
            """
        )
        raise
    except FileExistsError:
        errmsg = dedent(
            f"""
            EXPTDIR ({exptdir}) already exists, and PREEXISTING_DIR_METHOD = {preexisting_dir_method}

            To ignore this error, delete the directory, or set
            PREEXISTING_DIR_METHOD = delete, or
            PREEXISTING_DIR_METHOD = rename
            in your config file.
            """
        )
        raise FileExistsError(errmsg) from None

    #
    # -----------------------------------------------------------------------
    #
    # Set cron table entry for relaunching the workflow if
    # USE_CRON_TO_RELAUNCH is set to TRUE.
    #
    # -----------------------------------------------------------------------
    #
    if workflow_config.get("USE_CRON_TO_RELAUNCH"):
        intvl_mnts = workflow_config.get("CRON_RELAUNCH_INTVL_MNTS")
        launch_script_fn = workflow_config.get("WFLOW_LAUNCH_SCRIPT_FN")
        launch_log_fn = workflow_config.get("WFLOW_LAUNCH_LOG_FN")
        workflow_config["CRONTAB_LINE"] = (
            f"""*/{intvl_mnts} * * * * cd {exptdir} && """
            f"""./{launch_script_fn} called_from_cron="TRUE" >> ./{launch_log_fn} 2>&1"""
        )
    #
    # -----------------------------------------------------------------------
    #
    # Check user settings against platform settings
    #
    # -----------------------------------------------------------------------
    #

    # Before setting task flags, ensure we don't have any invalid rocoto tasks
    # (e.g. metatasks with no tasks, tasks with no associated commands)
    clean_rocoto_dict(expt_config["rocoto"]["tasks"])

    rocoto_config = expt_config.get('rocoto', {})
    rocoto_tasks = rocoto_config.get("tasks")
    run_make_grid = rocoto_tasks.get('task_make_grid') is not None
    run_make_orog = rocoto_tasks.get('task_make_orog') is not None
    run_make_sfc_climo = rocoto_tasks.get('task_make_sfc_climo') is not None

    # Also set some flags that will be needed later
    run_make_ics = dict_find(rocoto_tasks, "task_make_ics")
    run_make_lbcs = dict_find(rocoto_tasks, "task_make_lbcs")
    run_run_fcst = dict_find(rocoto_tasks, "task_run_fcst")
    run_any_coldstart_task = run_make_ics or \
                             run_make_lbcs or \
                             run_run_fcst
    run_run_post = dict_find(rocoto_tasks, "task_run_post")

    # Necessary tasks are turned on
    pregen_basedir = expt_config["platform"].get("DOMAIN_PREGEN_BASEDIR")
    if pregen_basedir is None and not (
        run_make_grid and run_make_orog and run_make_sfc_climo
    ):
        raise Exception(
            f"""
            DOMAIN_PREGEN_BASEDIR must be set when any of the following
            tasks are not included in the workflow:
                RUN_MAKE_GRID = {run_make_grid}
                RUN_MAKE_OROG = {run_make_orog}
                RUN_MAKE_SFC_CLIMO = {run_make_sfc_climo}"""
        )

    # A batch system account is specified
    if expt_config["platform"].get("WORKFLOW_MANAGER") is not None:
        if not expt_config.get("user").get("ACCOUNT"):
            raise Exception(
                dedent(
                    f"""
                  ACCOUNT must be specified in config or machine file if using a workflow manager.
                  WORKFLOW_MANAGER = {expt_config["platform"].get("WORKFLOW_MANAGER")}\n"""
                )
            )

    def _remove_tag(tasks, tag):
        """ Remove the tag for all the tasks in the workflow """

        if not isinstance(tasks, dict):
            return
        for task, task_settings in tasks.items():
            task_type = task.split("_", maxsplit=1)[0]
            if task_type == "task":
                task_settings.pop(tag, None)
            elif task_type == "metatask":
                _remove_tag(task_settings, tag)

    # Remove all memory tags for platforms that do not support them
    remove_memory = expt_config["platform"].get("REMOVE_MEMORY")
    if remove_memory:
        _remove_tag(rocoto_tasks, "memory")

    for part in ['PARTITION_HPSS', 'PARTITION_DEFAULT', 'PARTITION_FCST']:
        partition = expt_config["platform"].get(part)
        if not partition:
            _remove_tag(rocoto_tasks, 'partition')

    # When not running subhourly post, remove those tasks, if they exist
    if not expt_config.get("task_run_post", {}).get("SUB_HOURLY_POST"):
        post_meta = rocoto_tasks.get("metatask_run_ens_post", {})
        post_meta.pop("metatask_run_sub_hourly_post", None)
        post_meta.pop("metatask_sub_hourly_last_hour_post", None)


    date_first_cycl = workflow_config.get("DATE_FIRST_CYCL")
    date_last_cycl = workflow_config.get("DATE_LAST_CYCL")
    incr_cycl_freq = int(workflow_config.get("INCR_CYCL_FREQ"))
    cycl_intvl_dt = datetime.timedelta(hours=incr_cycl_freq)
    #
    # -----------------------------------------------------------------------
    #
    # If running vx tasks, check and possibly reset values in expt_config
    # and rocoto_config.
    #
    # -----------------------------------------------------------------------
    #
    if do_vx:
        #
        # -----------------------------------------------------------------------
        #
        # Set some variables needed for running checks on and creating new
        # (derived) configuration variables for the verification.
        #
        # -----------------------------------------------------------------------
        #
        vx_config = expt_config["verification"]
    
        fcst_len_hrs = workflow_config.get("FCST_LEN_HRS")
        vx_fcst_output_intvl_hrs = vx_config.get("VX_FCST_OUTPUT_INTVL_HRS")
    
        # To enable arithmetic with dates and times, convert various time
        # intervals from integer to datetime.timedelta objects.
        fcst_len_dt = datetime.timedelta(hours=fcst_len_hrs)
        vx_fcst_output_intvl_dt = datetime.timedelta(hours=vx_fcst_output_intvl_hrs)
        #
        # -----------------------------------------------------------------------
        #
        # Generate a list containing the starting times of the cycles.  This will
        # be needed in checking that the hours-of-day of the forecast output match
        # those of the observations.
        #
        # -----------------------------------------------------------------------
        #
        cycle_start_times \
        = set_cycle_dates(date_first_cycl, date_last_cycl, cycl_intvl_dt,
                          return_type='datetime')
        #
        # -----------------------------------------------------------------------
        #
        # Generate a list of forecast output times and a list of obs days (i.e.
        # days on which observations are needed to perform verification because
        # there is forecast output on those days) over all cycles, both for
        # instantaneous fields (e.g. T2m, REFC, RETOP) and for cumulative ones
        # (e.g. APCP).  Then add these lists to the dictionary containing workflow
        # configuration variables.  These will be needed in generating the ROCOTO
        # XML.
        #
        # -----------------------------------------------------------------------
        #
        fcst_output_times_all_cycles, obs_days_all_cycles, \
        = set_fcst_output_times_and_obs_days_all_cycles(
          cycle_start_times, fcst_len_dt, vx_fcst_output_intvl_dt)
    
        workflow_config['OBS_DAYS_ALL_CYCLES_INST'] = obs_days_all_cycles['inst']
        workflow_config['OBS_DAYS_ALL_CYCLES_CUMUL'] = obs_days_all_cycles['cumul']
        #
        # -----------------------------------------------------------------------
        #
        # Generate lists of ROCOTO cycledef strings corresonding to the obs days
        # for instantaneous fields and those for cumulative ones.  Then save the
        # lists of cycledefs in the dictionary containing values needed to
        # construct the ROCOTO XML.
        #
        # -----------------------------------------------------------------------
        #
        cycledefs_obs_days_inst = set_rocoto_cycledefs_for_obs_days(obs_days_all_cycles['inst'])
        cycledefs_obs_days_cumul = set_rocoto_cycledefs_for_obs_days(obs_days_all_cycles['cumul'])
    
        rocoto_config['cycledefs']['cycledefs_obs_days_inst'] = cycledefs_obs_days_inst
        rocoto_config['cycledefs']['cycledefs_obs_days_cumul'] = cycledefs_obs_days_cumul
        #
        # -----------------------------------------------------------------------
        #
        # Generate dictionary of dictionaries that, for each combination of obs
        # type needed and obs day, contains a string list of the times at which
        # that type of observation is needed on that day.  The elements of each
        # list are formatted as 'YYYYMMDDHH'.  This information is used by the
        # day-based get_obs tasks in the workflow to get obs only at those times
        # at which they are needed (as opposed to for the whole day).
        #
        # -----------------------------------------------------------------------
        #
        obs_retrieve_times_by_day \
        = get_obs_retrieve_times_by_day(
          vx_config, cycle_start_times, fcst_len_dt,
          fcst_output_times_all_cycles, obs_days_all_cycles)
    
        for obtype, obs_days_dict in obs_retrieve_times_by_day.items():
            for obs_day, obs_retrieve_times in obs_days_dict.items():
                array_name = '_'.join(["OBS_RETRIEVE_TIMES", obtype, obs_day])
                vx_config[array_name] = obs_retrieve_times
        expt_config["verification"] = vx_config
        #
        # -----------------------------------------------------------------------
        #
        # Remove all verification (meta)tasks for which no fields are specified.
        #
        # -----------------------------------------------------------------------
        #
        vx_field_groups_all_by_obtype = {}
        vx_metatasks_all_by_obtype = {}
    
        vx_field_groups_all_by_obtype["CCPA"] = ["APCP"]
        vx_metatasks_all_by_obtype["CCPA"] \
        = ["task_get_obs_ccpa",
           "metatask_PcpCombine_APCP_all_accums_obs_CCPA",
           "metatask_PcpCombine_APCP_all_accums_all_mems",
           "metatask_GridStat_APCP_all_accums_all_mems",
           "metatask_GenEnsProd_EnsembleStat_APCP_all_accums",
           "metatask_GridStat_APCP_all_accums_ensmeanprob"]
    
        vx_field_groups_all_by_obtype["NOHRSC"] = ["ASNOW"]
        vx_metatasks_all_by_obtype["NOHRSC"] \
        = ["task_get_obs_nohrsc",
           "metatask_PcpCombine_ASNOW_all_accums_obs_NOHRSC",
           "metatask_PcpCombine_ASNOW_all_accums_all_mems",
           "metatask_GridStat_ASNOW_all_accums_all_mems",
           "metatask_GenEnsProd_EnsembleStat_ASNOW_all_accums",
           "metatask_GridStat_ASNOW_all_accums_ensmeanprob"]
    
        vx_field_groups_all_by_obtype["MRMS"] = ["REFC", "RETOP"]
        vx_metatasks_all_by_obtype["MRMS"] \
        = ["task_get_obs_mrms",
           "metatask_GridStat_REFC_RETOP_all_mems",
           "metatask_GenEnsProd_EnsembleStat_REFC_RETOP",
           "metatask_GridStat_REFC_RETOP_ensprob"]
    
        vx_field_groups_all_by_obtype["NDAS"] = ["SFC", "UPA"]
        vx_metatasks_all_by_obtype["NDAS"] \
        = ["task_get_obs_ndas",
           "task_run_MET_Pb2nc_obs_NDAS",
           "metatask_PointStat_SFC_UPA_all_mems",
           "metatask_GenEnsProd_EnsembleStat_SFC_UPA",
           "metatask_PointStat_SFC_UPA_ensmeanprob"]

        vx_field_groups_all_by_obtype["AERONET"] = ["AOD"]
        vx_metatasks_all_by_obtype["AERONET"] \
        = ["task_get_obs_aeronet",
           "metatask_ASCII2nc_obs"]

        vx_field_groups_all_by_obtype["AIRNOW"] = ["PM25", "PM10"]
        vx_metatasks_all_by_obtype["AIRNOW"] \
        = ["task_get_obs_airnow",
           "metatask_ASCII2nc_obs",
           "metatask_PcpCombine_fcst_PM_all_mems"]

        # If there are no field groups specified for verification, remove those
        # tasks that are common to all observation types.
        vx_field_groups = vx_config["VX_FIELD_GROUPS"]
        if not vx_field_groups:
            metatask = "metatask_check_post_output_all_mems"
            rocoto_config['tasks'].pop(metatask)
    
        # If for a given obs type none of its field groups are specified for
        # verification, remove all vx metatasks for that obs type.
        for obtype in vx_field_groups_all_by_obtype:
            vx_field_groups_crnt_obtype = list(set(vx_field_groups) & set(vx_field_groups_all_by_obtype[obtype]))
            if not vx_field_groups_crnt_obtype:
                for metatask in vx_metatasks_all_by_obtype[obtype]:
                    if metatask in rocoto_config['tasks']:
                        logging.info(dedent(
                            f"""
                            Removing verification (meta)task
                              "{metatask}"
                            from workflow since no field groups from observation type "{obtype}" are
                            specified for verification."""
                        ))
                        rocoto_config['tasks'].pop(metatask)
        #
        # -----------------------------------------------------------------------
        #
        # If there are at least some field groups to verify, then make sure that
        # the base directories in which retrieved obs files will be placed are
        # distinct for the different obs types.
        #
        # -----------------------------------------------------------------------
        #
        if vx_field_groups:
            obtypes_all = ['CCPA', 'NOHRSC', 'MRMS', 'NDAS']
            obs_basedir_var_names = [f'{obtype}_OBS_DIR' for obtype in obtypes_all]
            obs_basedirs_dict = {key: vx_config[key] for key in obs_basedir_var_names}
            obs_basedirs_orig = list(obs_basedirs_dict.values())
            obs_basedirs_uniq = list(set(obs_basedirs_orig))
            if len(obs_basedirs_orig) != len(obs_basedirs_uniq):
                msg1 = dedent(f"""
                    The base directories for the obs files must be distinct, but at least two
                    are identical:""")
                msg2 = ''
                for obs_basedir_var_name, obs_dir in obs_basedirs_dict.items():
                    msg2 = msg2 + dedent(f"""
                        {obs_basedir_var_name} = {obs_dir}""")
                msg3 = dedent(f"""
                    Modify these in the SRW App's user configuration file to make them distinct
                    and rerun.
                    """)
                msg = msg1 + '    '.join(msg2.splitlines(True)) + msg3
                logging.error(msg)
                raise ValueError(msg)
    #
    # -----------------------------------------------------------------------
    #
    # The "cycled_from_second" cycledef in the default workflow configuration
    # file (default_workflow.yaml) requires the starting date of the second
    # cycle.  That is difficult to calculate in the yaml file itself because
    # currently, there are no utilities to perform arithmetic with dates.
    # Thus, we calculate it here and save it as a variable in the workflow
    # configuration dictionary.  Note that correct functioning of the default
    # workflow yaml file also requires that DATE_[FIRST|SECOND|LAST]_CYCL all
    # be strings, not datetime objects.  We perform those conversions here.
    #
    # -----------------------------------------------------------------------
    #
    date_second_cycl = date_first_cycl + cycl_intvl_dt
    workflow_config['DATE_FIRST_CYCL'] = datetime.datetime.strftime(date_first_cycl, "%Y%m%d%H")
    workflow_config['DATE_SECOND_CYCL'] = datetime.datetime.strftime(date_second_cycl, "%Y%m%d%H")
    workflow_config['DATE_LAST_CYCL'] = datetime.datetime.strftime(date_last_cycl, "%Y%m%d%H")
    #
    # -----------------------------------------------------------------------
    #
    # ICS and LBCS settings and validation
    #
    # -----------------------------------------------------------------------
    #
    def _get_location(xcs, fmt, expt_cfg):
        ics_lbcs = expt_cfg.get("data", {}).get("ics_lbcs")
        if ics_lbcs is not None:
            v = ics_lbcs.get(xcs)
            if not isinstance(v, dict):
                return v
            else:
                return v.get(fmt, "")
        else:
            return ""

    # Get the paths to any platform-supported data streams
    get_extrn_ics = expt_config.get("task_get_extrn_ics", {})
    extrn_mdl_sysbasedir_ics = _get_location(
        get_extrn_ics.get("EXTRN_MDL_NAME_ICS"),
        get_extrn_ics.get("FV3GFS_FILE_FMT_ICS"),
        expt_config,
    )
    get_extrn_ics["EXTRN_MDL_SYSBASEDIR_ICS"] = extrn_mdl_sysbasedir_ics

    get_extrn_lbcs = expt_config.get("task_get_extrn_lbcs", {})
    extrn_mdl_sysbasedir_lbcs = _get_location(
        get_extrn_lbcs.get("EXTRN_MDL_NAME_LBCS"),
        get_extrn_lbcs.get("FV3GFS_FILE_FMT_LBCS"),
        expt_config,
    )
    get_extrn_lbcs["EXTRN_MDL_SYSBASEDIR_LBCS"] = extrn_mdl_sysbasedir_lbcs

    # remove the data key -- it's not needed beyond this point
    if "data" in expt_config:
        expt_config.pop("data")

    # Check for the user-specified directories for external model files if
    # USE_USER_STAGED_EXTRN_FILES is set to TRUE
    task_keys = zip(
        [get_extrn_ics, get_extrn_lbcs],
        ["EXTRN_MDL_SOURCE_BASEDIR_ICS", "EXTRN_MDL_SOURCE_BASEDIR_LBCS"],
    )

    for task, data_key in task_keys:
        use_staged_extrn_files = task.get("USE_USER_STAGED_EXTRN_FILES")
        if use_staged_extrn_files:
            basedir = task[data_key]
            # Check for the base directory up to the first templated field.
            idx = basedir.find("$")
            if idx == -1:
                idx = len(basedir)

            if not os.path.exists(basedir[:idx]):
                raise FileNotFoundError(
                    f'''
                    The user-staged-data directory does not exist.
                    Please point to the correct path where your external
                    model files are stored.
                      {data_key} = \"{basedir}\"'''
                )


    # Make sure the vertical coordinate file and LEVP for both make_lbcs and make_ics is the same.
    if ics_vcoord := expt_config.get("task_make_ics", {}).get("VCOORD_FILE") != \
            (lbcs_vcoord := expt_config.get("task_make_lbcs", {}).get("VCOORD_FILE")):
         raise ValueError(
             f"""
             The VCOORD_FILE must be set to the same value for both the
             make_ics task and the make_lbcs task. They are currently
             set to:

             make_ics:
               VCOORD_FILE: {ics_vcoord}

             make_lbcs:
               VCOORD_FILE: {lbcs_vcoord}
             """
         )
    if ics_levp := expt_config.get("task_make_ics", {}).get("LEVP") != \
            (lbcs_levp := expt_config.get("task_make_lbcs", {}).get("LEVP")):
         raise ValueError(
             f"""
             The number of vertical levels LEVP must be set to the same value for both the
             make_ics task and the make_lbcs tasks. They are currently set to:

             make_ics:
               LEVP: {ics_levp}

             make_lbcs:
               LEVP: {lbcs_levp}
             """
         )

    #
    # -----------------------------------------------------------------------
    #
    # Forecast settings
    #
    # -----------------------------------------------------------------------
    #

    fcst_config = expt_config["task_run_fcst"]
    grid_config = expt_config["task_make_grid"]

    # Warn if user has specified a large timestep inappropriately
    hires_ccpp_suites = ["FV3_RRFS_v1beta","FV3_WoFS_v0", "FV3_HRRR", "FV3_HRRR_gf", "RRFS_sas"]
    if workflow_config["CCPP_PHYS_SUITE"] in hires_ccpp_suites:
        dt = fcst_config.get("DT_ATMOS")
        if dt:
            if dt > 40:
                logger.warning(dedent(
                    f"""
                    WARNING: CCPP suite {workflow_config["CCPP_PHYS_SUITE"]} requires short
                    time step regardless of grid resolution. The user-specified value
                    DT_ATMOS = {fcst_config.get("DT_ATMOS")}
                    may result in CFL violations or other errors!
                    """
                ))

    # Gather the pre-defined grid parameters, if needed
    if workflow_config.get("PREDEF_GRID_NAME"):
        grid_params = set_predef_grid_params(
            USHdir,
            workflow_config["PREDEF_GRID_NAME"],
            fcst_config["QUILTING"],
        )

        # Users like to change these variables, so don't overwrite them
        special_vars = ["DT_ATMOS", "LAYOUT_X", "LAYOUT_Y", "BLOCKSIZE"]
        for param, value in grid_params.items():
            if param in special_vars:
                param_val = fcst_config.get(param)
                if param_val and isinstance(param_val, str) and "{{" not in param_val:
                    continue
                elif isinstance(param_val, (int, float)):
                    continue
                # DT_ATMOS needs special treatment based on CCPP suite
                elif param == "DT_ATMOS":
                    if workflow_config["CCPP_PHYS_SUITE"] in hires_ccpp_suites and grid_params[param] > 40:
                        logger.warning(dedent(
                            f"""
                            WARNING: CCPP suite {workflow_config["CCPP_PHYS_SUITE"]} requires short
                            time step regardless of grid resolution; setting DT_ATMOS to 40.\n
                            This value can be overwritten in the user config file.
                            """
                        ))
                        fcst_config[param] = 40
                    else:
                        fcst_config[param] = value
                else:
                    fcst_config[param] = value
            elif param.startswith("WRTCMP"):
                if fcst_config.get(param) == "":
                    fcst_config[param] = value
            elif param == "GRID_GEN_METHOD":
                workflow_config[param] = value
            else:
                grid_config[param] = value

    run_envir = expt_config["user"].get("RUN_ENVIR", "")

    # set varying forecast lengths only when fcst_len_hrs=-1
    if fcst_len_hrs == -1:
        fcst_len_cycl = workflow_config.get("FCST_LEN_CYCL")

        # Check that the number of entries divides into a day
        if 24 / incr_cycl_freq != len(fcst_len_cycl):
            # Also allow for the possibility that the user is running
            # cycles for less than a day:
            num_cycles = len(set_cycle_dates(
                date_first_cycl,
                date_last_cycl,
                cycl_intvl_dt))

            if num_cycles != len(fcst_len_cycl):
              logger.error(f""" The number of entries in FCST_LEN_CYCL does
              not divide evenly into a 24 hour day or the number of cycles
              in your experiment!
                FCST_LEN_CYCL = {fcst_len_cycl}
              """
              )
              raise ValueError

        # Build cycledefs entries for the long forecasts
        # Short forecast cycles will be relevant to all intended
        # forecasts...after all, a 12 hour forecast also encompasses a 3
        # hour forecast, so the short ones will be consistent with the
        # existing default forecast cycledef

        # Reset the hours to the short forecast length
        workflow_config["FCST_LEN_HRS"] = min(fcst_len_cycl)

        # Find the entries that match the long forecast, and map them to
        # their time of day.
        long_fcst_len = max(fcst_len_cycl)
        long_indices = [i for i,x in enumerate(fcst_len_cycl) if x == long_fcst_len]
        long_cycles = [i * incr_cycl_freq for i in long_indices]

        # add one forecast entry per cycle per day
        fcst_cdef = []

        for hh in long_cycles:
            first = date_first_cycl.replace(hour=hh).strftime("%Y%m%d%H")
            last = date_last_cycl.replace(hour=hh).strftime("%Y%m%d%H")
            fcst_cdef.append(f'{first}00 {last}00 24:00:00')

        rocoto_config['cycledefs']['long_forecast'] = fcst_cdef

    # check the availability of restart intervals for restart capability of forecast
    do_fcst_restart = fcst_config.get("DO_FCST_RESTART")
    if do_fcst_restart:
        restart_interval = fcst_config.get("RESTART_INTERVAL")
        restart_hrs = []
        if " " in str(restart_interval):
            restart_hrs = restart_interval.split()
        else:
            restart_hrs.append(str(restart_interval))

        lbc_spec_intvl_hrs = expt_config["task_get_extrn_lbcs"]["LBC_SPEC_INTVL_HRS"]
        for irst in restart_hrs:
            rem_rst = int(irst) % lbc_spec_intvl_hrs
            if rem_rst != 0:
                raise Exception(
                    f"""
                The restart interval is not divided by LBC_SPEC_INTVL_HRS:
                  RESTART_INTERVAL = {irst}
                  LBC_SPEC_INTVL_HRS = {lbc_spec_intvl_hrs}"""
                )

    #
    # -----------------------------------------------------------------------
    #
    # Set parameters according to the type of horizontal grid generation
    # method specified.
    #
    # -----------------------------------------------------------------------
    #

    grid_gen_method = workflow_config["GRID_GEN_METHOD"]
    if grid_gen_method == "GFDLgrid":
        grid_params = set_gridparams_GFDLgrid(
            lon_of_t6_ctr=grid_config["GFDLgrid_LON_T6_CTR"],
            lat_of_t6_ctr=grid_config["GFDLgrid_LAT_T6_CTR"],
            res_of_t6g=grid_config["GFDLgrid_NUM_CELLS"],
            stretch_factor=grid_config["GFDLgrid_STRETCH_FAC"],
            refine_ratio_t6g_to_t7g=grid_config["GFDLgrid_REFINE_RATIO"],
            istart_of_t7_on_t6g=grid_config["GFDLgrid_ISTART_OF_RGNL_DOM_ON_T6G"],
            iend_of_t7_on_t6g=grid_config["GFDLgrid_IEND_OF_RGNL_DOM_ON_T6G"],
            jstart_of_t7_on_t6g=grid_config["GFDLgrid_JSTART_OF_RGNL_DOM_ON_T6G"],
            jend_of_t7_on_t6g=grid_config["GFDLgrid_JEND_OF_RGNL_DOM_ON_T6G"],
            verbose=verbose,
            nh4=expt_config["constants"]["NH4"],
            run_envir=run_envir,
        )
        expt_config["grid_params"] = grid_params
    elif grid_gen_method == "ESGgrid":
        grid_params = set_gridparams_ESGgrid(
            lon_ctr=grid_config["ESGgrid_LON_CTR"],
            lat_ctr=grid_config["ESGgrid_LAT_CTR"],
            nx=grid_config["ESGgrid_NX"],
            ny=grid_config["ESGgrid_NY"],
            pazi=grid_config["ESGgrid_PAZI"],
            halo_width=grid_config["ESGgrid_WIDE_HALO_WIDTH"],
            delx=grid_config["ESGgrid_DELX"],
            dely=grid_config["ESGgrid_DELY"],
            constants=expt_config["constants"],
        )
        expt_config["grid_params"] = grid_params
    elif not run_any_coldstart_task:
        logger.warning("No coldstart tasks specified, not setting grid parameters")
    else:
        errmsg = dedent(
            f"""
            Valid values of GRID_GEN_METHOD are GFDLgrid and ESGgrid.
            The value provided is:
              GRID_GEN_METHOD = {grid_gen_method}
            """
        )
        raise KeyError(errmsg) from None

    # Check to make sure that mandatory forecast variables are set.
    vlist = [
        "DT_ATMOS",
        "LAYOUT_X",
        "LAYOUT_Y",
        "BLOCKSIZE",
    ]
    if run_any_coldstart_task:
        for val in vlist:
            if not fcst_config.get(val):
                raise Exception(f"\nMandatory variable '{val}' has not been set\n")

    #
    # -----------------------------------------------------------------------
    #
    # Set magnitude of stochastic ad-hoc schemes to -999.0 if they are not
    # being used. This is required at the moment, since "do_shum/sppt/skeb"
    # does not override the use of the scheme unless the magnitude is also
    # specifically set to -999.0.  If all "do_shum/sppt/skeb" are set to
    # "false," then none will run, regardless of the magnitude values.
    #
    # -----------------------------------------------------------------------
    #
    global_sect = expt_config["global"]
    if not global_sect.get("DO_SHUM"):
        global_sect["SHUM_MAG"] = -999.0
    if not global_sect.get("DO_SKEB"):
        global_sect["SKEB_MAG"] = -999.0
    if not global_sect.get("DO_SPPT"):
        global_sect["SPPT_MAG"] = -999.0
    #
    # -----------------------------------------------------------------------
    #
    # If running with SPP in MYNN PBL, MYNN SFC, GSL GWD, Thompson MP, or
    # RRTMG, count the number of entries in SPP_VAR_LIST to correctly set
    # N_VAR_SPP, otherwise set it to zero.
    #
    # -----------------------------------------------------------------------
    #
    if global_sect.get("DO_SPP"):
        global_sect["N_VAR_SPP"] = len(global_sect["SPP_VAR_LIST"])
    else:
        global_sect["N_VAR_SPP"] = 0
    #
    # -----------------------------------------------------------------------
    #
    # If running with SPP, confirm that each SPP-related namelist value
    # contains the same number of entries as N_VAR_SPP (set above to be equal
    # to the number of entries in SPP_VAR_LIST).
    #
    # -----------------------------------------------------------------------
    #
    spp_vars = [
        "SPP_MAG_LIST",
        "SPP_LSCALE",
        "SPP_TSCALE",
        "SPP_SIGTOP1",
        "SPP_SIGTOP2",
        "SPP_STDDEV_CUTOFF",
        "ISEED_SPP",
    ]

    if global_sect.get("DO_SPP"):
        for spp_var in spp_vars:
            if len(global_sect[spp_var]) != global_sect["N_VAR_SPP"]:
                raise Exception(
                    f"""
                    All MYNN PBL, MYNN SFC, GSL GWD, Thompson MP, or RRTMG SPP-related namelist
                    variables must be of equal length to SPP_VAR_LIST:
                      SPP_VAR_LIST (length {global_sect['N_VAR_SPP']})
                      {spp_var} (length {len(global_sect[spp_var])})
                    """
                )
    #
    # -----------------------------------------------------------------------
    #
    # If running with Noah or RUC-LSM SPP, count the number of entries in
    # LSM_SPP_VAR_LIST to correctly set N_VAR_LNDP, otherwise set it to zero.
    # Also set LNDP_TYPE to 2 for LSM SPP, otherwise set it to zero.  Finally,
    # initialize an "FHCYC_LSM_SPP" variable to 0 and set it to 999 if LSM SPP
    # is turned on.  This requirement is necessary since LSM SPP cannot run with
    # FHCYC=0 at the moment, but FHCYC cannot be set to anything less than the
    # length of the forecast either.  A bug fix will be submitted to
    # ufs-weather-model soon, at which point, this requirement can be removed
    # from regional_workflow.
    #
    # -----------------------------------------------------------------------
    #
    if global_sect.get("DO_LSM_SPP"):
        global_sect["N_VAR_LNDP"] = len(global_sect["LSM_SPP_VAR_LIST"])
        global_sect["LNDP_TYPE"] = 2
        global_sect["LNDP_MODEL_TYPE"] = 2
        global_sect["FHCYC_LSM_SPP_OR_NOT"] = 999
    else:
        global_sect["N_VAR_LNDP"] = 0
        global_sect["LNDP_TYPE"] = 0
        global_sect["LNDP_MODEL_TYPE"] = 0
        global_sect["FHCYC_LSM_SPP_OR_NOT"] = 0
    #
    # -----------------------------------------------------------------------
    #
    # If running with LSM SPP, confirm that each LSM SPP-related namelist
    # value contains the same number of entries as N_VAR_LNDP (set above to
    # be equal to the number of entries in LSM_SPP_VAR_LIST).
    #
    # -----------------------------------------------------------------------
    #
    lsm_spp_vars = [
        "LSM_SPP_MAG_LIST",
        "LSM_SPP_LSCALE",
        "LSM_SPP_TSCALE",
    ]
    if global_sect.get("DO_LSM_SPP"):
        for lsm_spp_var in lsm_spp_vars:
            if len(global_sect[lsm_spp_var]) != global_sect["N_VAR_LNDP"]:
                raise Exception(
                    f"""
                    All MYNN PBL, MYNN SFC, GSL GWD, Thompson MP, or RRTMG SPP-related namelist
                    variables must be of equal length to SPP_VAR_LIST:
                    All Noah or RUC-LSM SPP-related namelist variables (except ISEED_LSM_SPP)
                    must be equal of equal length to LSM_SPP_VAR_LIST:
                      LSM_SPP_VAR_LIST (length {global_sect['N_VAR_LNDP']})
                      {lsm_spp_var} (length {len(global_sect[lsm_spp_var])}
                      """
                )

    # Check whether the forecast length (FCST_LEN_HRS) is evenly divisible
    # by the BC update interval (LBC_SPEC_INTVL_HRS). If so, generate an
    # array of forecast hours at which the boundary values will be updated.

    lbc_spec_intvl_hrs = get_extrn_lbcs.get("LBC_SPEC_INTVL_HRS")
    rem = fcst_len_hrs % lbc_spec_intvl_hrs
    if rem != 0 and fcst_len_hrs > 0:
        raise Exception(
            f"""
            The forecast length (FCST_LEN_HRS) is not evenly divisible by the lateral
            boundary conditions update interval (LBC_SPEC_INTVL_HRS):
              FCST_LEN_HRS = {fcst_len_hrs}
              LBC_SPEC_INTVL_HRS = {lbc_spec_intvl_hrs}
              rem = FCST_LEN_HRS%%LBC_SPEC_INTVL_HRS = {rem}"""
        )

    #
    # -----------------------------------------------------------------------
    #
    # Post-processing validation and settings
    #
    # -----------------------------------------------------------------------
    #

    # If using a custom post configuration file, make sure that it exists.
    post_config = expt_config["task_run_post"]
    if post_config.get("USE_CUSTOM_POST_CONFIG_FILE"):
        custom_post_config_fp = post_config.get("CUSTOM_POST_CONFIG_FP")
        try:
            # os.path.exists returns exception if passed None, so use
            # "try/except" to catch it and the non-existence of a
            # provided path
            if not os.path.exists(custom_post_config_fp):
                raise FileNotFoundError(
                    dedent(
                        f"""
                    USE_CUSTOM_POST_CONFIG_FILE has been set, but the custom post configuration file
                    CUSTOM_POST_CONFIG_FP = {custom_post_config_fp}
                    could not be found."""
                    )
                ) from None
        except TypeError:
            raise TypeError(
                dedent(
                    f"""
                USE_CUSTOM_POST_CONFIG_FILE has been set, but the custom
                post configuration file path (CUSTOM_POST_CONFIG_FP) is
                None.
                """
                )
            ) from None
        except FileNotFoundError:
            raise

    # If using external CRTM fix files to allow post-processing of synthetic
    # satellite products from the UPP, make sure the CRTM fix file directory exists.
    if global_sect.get("USE_CRTM"):
        crtm_dir = global_sect.get("CRTM_DIR")
        try:
            # os.path.exists returns exception if passed None, so use
            # "try/except" to catch it and the non-existence of a
            # provided path
            if not os.path.exists(crtm_dir):
                raise FileNotFoundError(
                    dedent(
                        f"""
                    USE_CRTM has been set, but the external CRTM fix file directory:
                    CRTM_DIR = {crtm_dir}
                    could not be found."""
                    )
                ) from None
        except TypeError:
            raise TypeError(
                dedent(
                    f"""
                USE_CRTM has been set, but the external CRTM fix file
                directory (CRTM_DIR) is None.
                """
                )
            ) from None
        except FileNotFoundError:
            raise

    # If performing sub-hourly model output and post-processing, check that
    # the output interval DT_SUBHOURLY_POST_MNTS (in minutes) is specified
    # correctly.
    if post_config.get("SUB_HOURLY_POST"):

        # Subhourly post should be set with minutes between 1 and 59 for
        # real subhourly post to be performed.
        dt_subhourly_post_mnts = post_config.get("DT_SUBHOURLY_POST_MNTS")
        if dt_subhourly_post_mnts == 0:
            logger.warning(
                f"""
                When performing sub-hourly post (i.e. SUB_HOURLY_POST set to \"TRUE\"),
                DT_SUBHOURLY_POST_MNTS must be set to a value greater than 0; otherwise,
                sub-hourly output is not really being performed:
                  DT_SUBHOURLY_POST_MNTS = \"{DT_SUBHOURLY_POST_MNTS}\"
                Resetting SUB_HOURLY_POST to \"FALSE\".  If you do not want this, you
                must set DT_SUBHOURLY_POST_MNTS to something other than zero."""
            )
            post_config["SUB_HOURLY_POST"] = False

        if dt_subhourly_post_mnts < 1 or dt_subhourly_post_mnts > 59:
            raise ValueError(
                f'''
                When SUB_HOURLY_POST is set to \"TRUE\",
                DT_SUBHOURLY_POST_MNTS must be set to an integer between 1 and 59,
                inclusive but:
                  DT_SUBHOURLY_POST_MNTS = \"{dt_subhourly_post_mnts}\"'''
            )

        # Check that DT_SUBHOURLY_POST_MNTS (after converting to seconds) is
        # evenly divisible by the forecast model's main time step DT_ATMOS.
        dt_atmos = fcst_config["DT_ATMOS"]
        rem = dt_subhourly_post_mnts * 60 % dt_atmos
        if rem != 0:
            raise ValueError(
                f"""
                When SUB_HOURLY_POST is set to \"TRUE\") the post
                processing interval in seconds must be evenly divisible
                by the time step DT_ATMOS used in the forecast model,
                i.e. the remainder must be zero.  In this case, it is
                not:

                  DT_SUBHOURLY_POST_MNTS = \"{dt_subhourly_post_mnts}\"
                  DT_ATMOS = \"{dt_atmos}\"
                  remainder = (DT_SUBHOURLY_POST_MNTS*60) %% DT_ATMOS = {rem}

                Please reset DT_SUBHOURLY_POST_MNTS and/or DT_ATMOS so
                that this remainder is zero."""
            )

    # Make sure the post output domain is set
    predef_grid_name = workflow_config.get("PREDEF_GRID_NAME")
    post_output_domain_name = post_config.get("POST_OUTPUT_DOMAIN_NAME")

    if not post_output_domain_name:
        if not predef_grid_name and run_run_post:
            raise Exception(
                f"""
                The domain name used in naming the run_post output files
                (POST_OUTPUT_DOMAIN_NAME) has not been set:
                POST_OUTPUT_DOMAIN_NAME = \"{post_output_domain_name}\"
                If this experiment is not using a predefined grid (i.e. if
                PREDEF_GRID_NAME is set to a null string), POST_OUTPUT_DOMAIN_NAME
                must be set in the configuration file (\"{user_config_fn}\"). """
            )
        post_output_domain_name = predef_grid_name

    if not isinstance(post_output_domain_name, int):
        post_output_domain_name = lowercase(post_output_domain_name)

    # Write updated value of POST_OUTPUT_DOMAIN_NAME back to dictionary
    post_config["POST_OUTPUT_DOMAIN_NAME"] = post_output_domain_name

    #
    # -----------------------------------------------------------------------
    #
    # Set the output directory locations
    #
    # -----------------------------------------------------------------------
    #
    # Use env variables for NCO variables and create NCO directories
    workflow_manager = expt_config["platform"].get("WORKFLOW_MANAGER")
    if run_envir == "nco" and workflow_manager == "rocoto":
        # Update the rocoto string for the fcst output location if
        # running an ensemble in nco mode
        if global_sect["DO_ENSEMBLE"]:
            rocoto_config["entities"]["FCST_DIR"] = \
                "{{ nco.PTMP }}/{{ nco.envir_default }}/tmp/run_fcst_mem#mem#.{{ workflow.WORKFLOW_ID }}_@Y@m@d@H"

    # create experiment dir
    mkdir_vrfy(f' -p "{exptdir}"')

    # -----------------------------------------------------------------------
    #
    # The FV3 forecast model needs the following input files in the run
    # directory to start a forecast:
    #
    #   (1) The data table file
    #   (2) The diagnostics table file
    #   (3) The field table file
    #   (4) The FV3 namelist file
    #   (5) The model configuration file
    #   (6) The NEMS configuration file
    #   (7) The CCPP physics suite definition file
    #
    # The workflow contains templates for the first six of these files.
    # Template files are versions of these files that contain placeholder
    # (i.e. dummy) values for various parameters.  The experiment/workflow
    # generation scripts copy these templates to appropriate locations in
    # the experiment directory (either the top of the experiment directory
    # or one of the cycle subdirectories) and replace the placeholders in
    # these copies by actual values specified in the experiment/workflow
    # configuration file (or derived from such values).  The scripts then
    # use the resulting "actual" files as inputs to the forecast model.
    #
    # Note that the CCPP physics suite definition file does not have a
    # corresponding template file because it does not contain any values
    # that need to be replaced according to the experiment/workflow
    # configuration.  If using CCPP, this file simply needs to be copied
    # over from its location in the forecast model's directory structure
    # to the experiment directory.
    #
    # Below, we first set the names of the templates for the first six files
    # listed above.  We then set the full paths to these template files.
    # Note that some of these file names depend on the physics suite while
    # others do not.
    #
    # -----------------------------------------------------------------------
    #
    # Check for the CCPP_PHYSICS suite xml file
    ccpp_phys_suite_in_ccpp_fp = workflow_config["CCPP_PHYS_SUITE_IN_CCPP_FP"]
    if not os.path.exists(ccpp_phys_suite_in_ccpp_fp):
        raise FileNotFoundError(
            f"""
            The CCPP suite definition file (CCPP_PHYS_SUITE_IN_CCPP_FP) does not exist
            in the local clone of the ufs-weather-model:
              CCPP_PHYS_SUITE_IN_CCPP_FP = '{ccpp_phys_suite_in_ccpp_fp}'"""
        )

    # Check for the field dict file
    field_dict_in_uwm_fp = workflow_config["FIELD_DICT_IN_UWM_FP"]
    if not os.path.exists(field_dict_in_uwm_fp):
        raise FileNotFoundError(
            f"""
            The field dictionary file (FIELD_DICT_IN_UWM_FP) does not exist
            in the local clone of the ufs-weather-model:
              FIELD_DICT_IN_UWM_FP = '{field_dict_in_uwm_fp}'"""
        )

    #
    # -----------------------------------------------------------------------
    #
    # Check that the set of tasks to run in the workflow is internally
    # consistent.
    #
    # -----------------------------------------------------------------------
    #
    # Get list of all top-level tasks and metatasks in the workflow.
    task_defs = rocoto_config.get('tasks')
    all_tasks = [task for task in task_defs]

    # Get list of all valid top-level tasks and metatasks pertaining to ensemble
    # verification.
    ens_vx_task_defns = load_config_file(
      os.path.join(USHdir, os.pardir, "parm", "wflow", "verify_ens.yaml"))
    ens_vx_valid_tasks = [task for task in ens_vx_task_defns]

    # Get list of all valid top-level tasks and metatasks in the workflow that
    # pertain to ensemble verification.
    ens_vx_tasks = [task for task in ens_vx_valid_tasks if task in all_tasks]

    # Get the value of the configuration flag for ensemble mode (DO_ENSEMBLE)
    # and ensure that it is set to True if ensemble vx tasks are included in
    # the workflow (or vice-versa).
    do_ensemble = global_sect["DO_ENSEMBLE"]
    if (not do_ensemble) and ens_vx_tasks:
        task_str = "    " + "\n    ".join(ens_vx_tasks)
        msg = dedent(f"""
              Ensemble verification can not be run unless running in ensemble mode:
                  DO_ENSEMBLE = \"{do_ensemble}\"
              Ensemble verification tasks:
              """)
        msg = "".join([msg, task_str, dedent(f"""
              Please set DO_ENSEMBLE to True or remove ensemble vx tasks from the
              workflow.""")])
        raise Exception(msg)

    #
    # -----------------------------------------------------------------------
    # NOTE: currently this is executed no matter what, should it be dependent on the logic described below??
    # If not running the TN_MAKE_GRID, TN_MAKE_OROG, and/or TN_MAKE_SFC_CLIMO
    # tasks, create symlinks under the FIXlam directory to pregenerated grid,
    # orography, and surface climatology files.
    #
    # -----------------------------------------------------------------------
    #
    fixlam = workflow_config["FIXlam"]
    mkdir_vrfy(f' -p "{fixlam}"')

    #
    # Use the pregenerated domain files if the tasks to generate them
    # are turned off. Link the files, and check that they all contain
    # the same resolution input.
    #

    # Flags for creating symlinks to pre-generated grid, orography, and sfc_climo files.
    # These consider dependencies of other tasks on each pre-processing task.
    create_symlinks_to_pregen_files = {
      "GRID": (not run_make_grid) and \
              (run_make_orog or run_make_sfc_climo or run_any_coldstart_task),
      "OROG": (not run_make_orog) and \
              (run_make_sfc_climo or run_any_coldstart_task),
      "SFC_CLIMO": (not run_make_sfc_climo) and \
                   (run_make_ics or run_make_lbcs),
    }

    fixed_files = expt_config["fixed_files"]

    prep_tasks = ["GRID", "OROG", "SFC_CLIMO"]
    res_in_fixlam_filenames = None
    for prep_task in prep_tasks:
        res_in_fns = ""
        # If the user doesn't want to run the given task, link the fix
        # file from the staged files.
        if create_symlinks_to_pregen_files[prep_task]:
            sect_key = f"task_make_{prep_task.lower()}"
            dir_key = f"{prep_task}_DIR"
            task_dir = expt_config[sect_key].get(dir_key)

            if not task_dir:
                task_dir = os.path.join(pregen_basedir, predef_grid_name)
                expt_config[sect_key][dir_key] = task_dir
                msg = dedent(
                    f"""
                   {dir_key} will point to a location containing pre-generated files.
                   Setting {dir_key} = {task_dir}
                   """
                )
                logger.warning(msg)

            if not os.path.exists(task_dir):
                msg = dedent(
                    f"""
                    File directory does not exist!
                    {dir_key} needs {task_dir}
                    """
                )
                raise FileNotFoundError(msg)

            # Link the fix files and check that their resolution is
            # consistent
            res_in_fns = link_fix(
                verbose=verbose,
                file_group=prep_task.lower(),
                source_dir=task_dir,
                target_dir=workflow_config["FIXlam"],
                ccpp_phys_suite=workflow_config["CCPP_PHYS_SUITE"],
                constants=expt_config["constants"],
                dot_or_uscore=workflow_config["DOT_OR_USCORE"],
                nhw=grid_params["NHW"],
                run_task=False,
                sfc_climo_fields=fixed_files["SFC_CLIMO_FIELDS"],
            )
            if not res_in_fixlam_filenames:
                res_in_fixlam_filenames = res_in_fns
            else:
                if res_in_fixlam_filenames != res_in_fns:
                    raise Exception(
                        dedent(
                            f"""
                        The resolution of the pregenerated files for
                        {prep_task} do not match those that were alread
                        set:

                        Resolution in {prep_task}: {res_in_fns}
                        Resolution expected: {res_in_fixlam_filenames}
                        """
                        )
                    )

            if not os.path.exists(task_dir):
                raise FileNotFoundError(
                    f'''
                    The directory ({dir_key}) that should contain the pregenerated
                    {prep_task.lower()} files does not exist:
                      {dir_key} = \"{task_dir}\"'''
                )

    workflow_config["RES_IN_FIXLAM_FILENAMES"] = res_in_fixlam_filenames
    workflow_config["CRES"] = f"C{res_in_fixlam_filenames}"

    #
    # -----------------------------------------------------------------------
    #
    # Turn off post task if it's not consistent with the forecast's
    # user-setting of WRITE_DOPOST
    #
    # -----------------------------------------------------------------------
    #
    if fcst_config["WRITE_DOPOST"]:
        # Turn off run_post
        task_name = 'metatask_run_ens_post'
        removed_task = task_defs.pop(task_name, None)
        if removed_task:
            logger.warning(
                dedent(
                    f"""
                     Inline post is turned on, deactivating post-processing tasks:
                     Removing {task_name} from task definitions
                     list.
                     """
                )
            )

        # Check if SUB_HOURLY_POST is on
        if expt_config["task_run_post"]["SUB_HOURLY_POST"]:
            raise Exception(
                f"""
                SUB_HOURLY_POST is NOT available with Inline Post yet."""
            )

    #
    # -----------------------------------------------------------------------
    #
    # Read CCPP suite definition file and perform actions based on its
    # contents as necessary
    #
    # -----------------------------------------------------------------------
    #

    ccpp_suite_xml = load_xml_file(workflow_config["CCPP_PHYS_SUITE_IN_CCPP_FP"])

    # Need to track if we are using RUC LSM for the make_ics step
    workflow_config["SDF_USES_RUC_LSM"] = has_tag_with_value(ccpp_suite_xml, "scheme", "lsm_ruc")

    # Thompson microphysics needs additional input files and namelist settings
    workflow_config["SDF_USES_THOMPSON_MP"] = has_tag_with_value(ccpp_suite_xml, "scheme", "mp_thompson")

    if workflow_config["SDF_USES_THOMPSON_MP"]:
    
        logger.debug(f'Selected CCPP suite ({workflow_config["CCPP_PHYS_SUITE"]}) uses Thompson MP')
        logger.debug(f'Setting up links for additional fix files')

        # If the model ICs or BCs are not from RAP or HRRR, they will not contain aerosol
        # climatology data needed by the Thompson scheme, so we need to provide a separate file
        if (get_extrn_ics["EXTRN_MDL_NAME_ICS"] not in ["HRRR", "RRFS", "RAP"] or
           get_extrn_lbcs["EXTRN_MDL_NAME_LBCS"] not in ["HRRR", "RRFS", "RAP"]):
            fixed_files["THOMPSON_FIX_FILES"].append(workflow_config["THOMPSON_MP_CLIMO_FN"])

        # Add thompson-specific fix files to CYCLEDIR_LINKS_TO_FIXam_FILES_MAPPING and
        # FIXgsm_FILES_TO_COPY_TO_FIXam; see parm/fixed_files_mapping.yaml for more info on these variables

        fixed_files["FIXgsm_FILES_TO_COPY_TO_FIXam"].extend(fixed_files["THOMPSON_FIX_FILES"])

        for fix_file in fixed_files["THOMPSON_FIX_FILES"]:
            fixed_files["CYCLEDIR_LINKS_TO_FIXam_FILES_MAPPING"].append(f"{fix_file} | {fix_file}")

        logger.debug(f'New fix file list:\n{fixed_files["FIXgsm_FILES_TO_COPY_TO_FIXam"]=}')
        logger.debug(f'New fix file mapping:\n{fixed_files["CYCLEDIR_LINKS_TO_FIXam_FILES_MAPPING"]=}')


    # -----------------------------------------------------------------------
    #
    # Check that UFS FIRE settings are correct and consistent
    #
    # -----------------------------------------------------------------------
    fire_conf = expt_config["fire"]
    if fire_conf["UFS_FIRE"]:
        if build_config["Application"]!="ATMF":
            raise Exception("UFS_FIRE == True but UFS SRW has not been built for fire coupling; see users guide for details")
        fire_input_file=os.path.join(fire_conf["FIRE_INPUT_DIR"],"geo_em.d01.nc")
        if not os.path.isfile(fire_input_file):
            raise FileNotFoundError(
                dedent(
                    f"""
                The fire input file (geo_em.d01.nc) does not exist in the specified directory:
                {fire_conf["FIRE_INPUT_DIR"]}
                Check that the specified path is correct, and that the file exists and is readable
                """
                )
            )
        if fire_conf["FIRE_NUM_TASKS"] < 1:
            raise ValueError("FIRE_NUM_TASKS must be > 0 if UFS_FIRE is True")
        elif fire_conf["FIRE_NUM_TASKS"] > 1:
            raise ValueError("FIRE_NUM_TASKS > 1 not yet supported")

        if fire_conf["FIRE_NUM_IGNITIONS"] > 5:
            raise ValueError(f"Only 5 or fewer fire ignitions supported")

        if fire_conf["FIRE_NUM_IGNITIONS"] > 1:
            # These settings all need to be lists for multiple fire ignitions
            each_fire = ["FIRE_IGNITION_ROS", "FIRE_IGNITION_START_LAT", "FIRE_IGNITION_START_LON",
                         "FIRE_IGNITION_END_LAT", "FIRE_IGNITION_END_LON", "FIRE_IGNITION_RADIUS",
                         "FIRE_IGNITION_START_TIME", "FIRE_IGNITION_END_TIME"]
            for setting in each_fire:
                if not isinstance(fire_conf[setting], list):
                    logger.critical(f"{fire_conf['FIRE_NUM_IGNITIONS']=}")
                    logger.critical(f"{fire_conf[setting]=}")
                    raise ValueError(f"For FIRE_NUM_IGNITIONS > 1, {setting} must be a list of the same length")
                if len(fire_conf[setting]) != fire_conf["FIRE_NUM_IGNITIONS"]:
                    logger.critical(f"{fire_conf['FIRE_NUM_IGNITIONS']=}")
                    logger.critical(f"{fire_conf[setting]=}")
                    raise ValueError(f"For FIRE_NUM_IGNITIONS > 1, {setting} must be a list of the same length")

        if fire_conf["FIRE_ATM_FEEDBACK"] < 0.0:
            raise ValueError("FIRE_ATM_FEEDBACK must be 0 or greater")

        if fire_conf["FIRE_UPWINDING"] == 0 and fire_conf["FIRE_VISCOSITY"] == 0.0:
            raise ValueError("FIRE_VISCOSITY must be > 0.0 if FIRE_UPWINDING == 0")
    else:
        if fire_conf["FIRE_NUM_TASKS"] > 0:
            logger.warning("UFS_FIRE is not enabled; setting FIRE_NUM_TASKS = 0")
            fire_conf["FIRE_NUM_TASKS"] = 0
    #
    # -----------------------------------------------------------------------
    #
    # Generate var_defns.yaml file in the EXPTDIR. This file contains all
    # the user-specified settings from expt_config.
    #
    # -----------------------------------------------------------------------
    #

    extend_yaml(expt_config)
    for sect, sect_keys in expt_config.items():
        for k, v in sect_keys.items():
            expt_config[sect][k] = str_to_list(v)
    extend_yaml(expt_config)

    # print content of var_defns if DEBUG=True
    all_lines = cfg_to_yaml_str(expt_config)
    logger.debug(all_lines)

    global_var_defns_fp = workflow_config["GLOBAL_VAR_DEFNS_FP"]
    # print info message
    logger.info(
        f"""
        Generating the global experiment variable definitions file here:
          GLOBAL_VAR_DEFNS_FP = '{global_var_defns_fp}'
        For more detailed information, set DEBUG to 'TRUE' in the experiment
        configuration file ('{user_config_fn}')."""
    )

    # Final failsafe before writing rocoto yaml to ensure we don't have any invalid dicts
    # (e.g. metatasks with no tasks, tasks with no associated commands)
    clean_rocoto_dict(expt_config["rocoto"]["tasks"])

    rocoto_yaml_fp = workflow_config["ROCOTO_YAML_FP"]
    with open(rocoto_yaml_fp, 'w') as f:
        yaml.Dumper.ignore_aliases = lambda *args : True
        yaml.dump(expt_config.get("rocoto"), f, sort_keys=False)

    var_defns_cfg = get_yaml_config(config=expt_config)
    del var_defns_cfg["rocoto"]

    # Fixup a couple of data types:
    for dates in ("DATE_FIRST_CYCL", "DATE_LAST_CYCL"):
        var_defns_cfg["workflow"][dates] = date_to_str(var_defns_cfg["workflow"][dates])
    var_defns_cfg.dump(global_var_defns_fp)

    # Generate a flag file for cold start
    if expt_config["workflow"].get("COLDSTART"):
        coldstart_date = var_defns_cfg["workflow"]["DATE_FIRST_CYCL"]
        fn_pass=f"task_skip_coldstart_{coldstart_date}.txt"
        open(os.path.join(exptdir,fn_pass), 'a').close()

    #
    # -----------------------------------------------------------------------
    #
    # Check validity of parameters in one place, here in the end.
    #
    # -----------------------------------------------------------------------
    #

    # loop through the flattened expt_config and check validity of params
    cfg_v = load_config_file(os.path.join(USHdir, "valid_param_vals.yaml"))
    for k, v in flatten_dict(expt_config).items():
        if v is None or v == "":
            continue
        vkey = "valid_vals_" + k
        if (vkey in cfg_v):
            if (type(v) == list):
                if not(all(ele in cfg_v[vkey] for ele in v)):
                    raise Exception(
                        dedent(f"""
                        The variable
                            {k} = {v}
                        in the user's configuration has at least one invalid value.  Possible values are:
                            {k} = {cfg_v[vkey]}"""
                    ))
            else:
                if not (v in cfg_v[vkey]):
                    raise Exception(
                        dedent(f"""
                        The variable
                            {k} = {v}
                        in the user's configuration does not have a valid value.  Possible values are:
                            {k} = {cfg_v[vkey]}"""
                    ))

    return expt_config

def clean_rocoto_dict(rocotodict):
    """Removes any invalid entries from ``rocotodict``. Examples of invalid entries are:

    1. A task dictionary containing no "command" key
    2. A metatask dictionary containing no task dictionaries

    Args:
        rocotodict (dict): A dictionary containing Rocoto workflow settings
    """

    # Loop 1: search for tasks with no command key, iterating over metatasks
    for key in list(rocotodict.keys()):
        if key.split("_", maxsplit=1)[0] == "metatask":
            clean_rocoto_dict(rocotodict[key])
        elif key.split("_", maxsplit=1)[0] in ["task"]:
            if not rocotodict[key].get("command"):
                popped = rocotodict.pop(key)
                logging.warning(f"Invalid task {key} removed due to empty/unset run command")
                logging.debug(f"Removed entry:\n{popped}")

    # Loop 2: search for metatasks with no tasks in them
    for key in list(rocotodict.keys()):
        if key.split("_", maxsplit=1)[0] == "metatask":
            valid = False
            for key2 in list(rocotodict[key].keys()):
                if key2.split("_", maxsplit=1)[0] == "metatask":
                    clean_rocoto_dict(rocotodict[key][key2])
                    #After above recursion, any nested empty metatasks will have popped themselves
                    if rocotodict[key].get(key2):
                        valid = True
                elif key2.split("_", maxsplit=1)[0] == "task":
                    valid = True
            if not valid:
                popped = rocotodict.pop(key)
                logging.warning(f"Invalid/empty metatask {key} removed")
                logging.debug(f"Removed entry:\n{popped}")



#
# -----------------------------------------------------------------------
#
# Call the function defined above.
#
# -----------------------------------------------------------------------
#
if __name__ == "__main__":
    USHdir = os.path.dirname(os.path.abspath(__file__))
    setup(USHdir)
