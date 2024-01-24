help([[
This load("s libraries for building the UFS SRW App 
using singularity container with intel-oneapi
]])

whatis([===[Loads libraries needed for building the UFS SRW App in a singularity container ]===])

prepend_path("MODULEPATH", "/opt/spack-stack/spack-stack-1.4.1/envs/unified-dev/install/modulefiles/Core")
load("stack-intel")
load("stack-intel-oneapi-mpi")
load("cmake/3.23.1")

load("srw_common")
setenv("CMAKE_C_COMPILER","mpiicc")
setenv("CMAKE_CXX_COMPILER","mpiicpc")
setenv("CMAKE_Fortran_COMPILER","mpiifort")
setenv("CMAKE_Platform","singularity.intel")

