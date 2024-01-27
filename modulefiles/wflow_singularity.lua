help([[
This module loads python environement for running the UFS SRW App in
a singularity container
]])

whatis([===[Loads libraries needed for running the UFS SRW App in a singularity container]===])
load("set_pythonpath")

prepend_path("MODULEPATH","/home/ubuntu/rocoto/modulefiles")
load("rocoto")

append_path("MODULEPATH","/home/ubuntu/miniconda3/modulefiles")
load("miniconda3")

setenv("PROJ_LIB","/home/ubuntu/miniconda3/4.12.0/envs/regional_workflow/share/proj")
append_path("PATH","/home/ubuntu/miniconda3/4.12.0/envs/regional_workflow/bin")

if mode() == "load" then
   execute{cmd="conda activate workflow_tools", modeA={"load"}}
end
