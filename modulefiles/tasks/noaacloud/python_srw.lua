--unload("python")
--append_path("MODULEPATH","/contrib/EPIC/miniconda3/modulefiles")
--load(pathJoin("miniconda3", os.getenv("miniconda3_ver") or "4.12.0"))
--setenv("SRW_ENV", "workflow_tools")
load("conda")
setenv("SRW_ENV", "srw_app")
