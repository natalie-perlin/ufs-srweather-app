unload("miniconda3")
prepend_path("MODULEPATH","/home/ubuntu/miniconda3/modulefiles")
load(pathJoin("miniconda3", os.getenv("miniconda3_ver") or "4.12.0"))

setenv("SRW_ENV", "workflow_tools")
