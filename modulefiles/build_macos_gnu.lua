help([[
This module needs to be customized for the user's MacOS environment:
specify compilers, path for HPC-stack, load the modules, set compiler and linker flags
]])

whatis([===[Loads libraries needed for building the UFS SRW App on macos ]===])

if mode() == "load" then
   execute{cmd="ulimit -S -s unlimited", modeA={"load"}}
end


prepend_path("MODULEPATH", "/Users/ssm-user/spack-stack/spack-stack-1.8.0/envs/ufs-wm-env/install/modulefiles/Core")

stack_gnu_ver=os.getenv("stack_apple_clang_ver") or "15.0.0"
load(pathJoin("stack-apple-clang", stack_gnu_ver))

stack_openmpi_ver=os.getenv("stack_openmpi_ver") or "4.1.6"
load(pathJoin("stack-openmpi", stack_openmpi_ver))

-- cmake_ver=os.getenv("cmake_ver") or "3.27.9"
-- load(pathJoin("cmake", cmake_ver))
load("cmake")

load("srw_common")

setenv("CC", "mpicc")
setenv("CXX", "mpicxx")
setenv("F90", "mpif90")
setenv("FC", "mpifort")
setenv("CPP", "${F90} -E -x f95-cpp-input")
setenv("CMAKE_Platform", "macosx.gnu")
setenv("VERBOSE","1")
setenv("BUILD_VERBOSE","1")

-- Set compilers and platform names for CMake:
setenv("CMAKE_C_COMPILER", "mpicc")
setenv("CMAKE_CXX_COMPILER", "mpicxx")
setenv("CMAKE_Fortran_COMPILER", "mpifort")
setenv("CMAKE_Fortran_COMPILER_ID", "GNU")

setenv("CFLAGS","-Wno-implicit-function-declaration ")

