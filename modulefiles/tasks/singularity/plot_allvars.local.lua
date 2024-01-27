unload("miniconda3")
prepend_path("MODULEPATH","/home/ubuntu/miniconda3/modulefiles")
load(pathJoin("miniconda3", os.getenv("miniconda3_ver") or "4.12.0"))

setenv("PROJ_LIB","/home/ubuntu/miniconda3/4.12.0/envs/regional_workflow/share/proj")
append_path("PATH","/home/ubuntu/miniconda3/4.12.0/envs/regional_workflow/bin")

setenv("SRW_ENV", "regional_workflow")
