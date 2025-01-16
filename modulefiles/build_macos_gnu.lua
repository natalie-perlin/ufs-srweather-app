help([[
This module needs to be customized for the user's MacOS environment:
specify compilers, path for HPC-stack, load the modules, set compiler and linker flags
]])

whatis([===[Loads libraries needed for building the UFS SRW App on macos ]===])

if mode() == "load" then
   execute{cmd="ulimit -S -s unlimited", modeA={"load"}}
end

-- Replace the stackpath below by the path of the local spack-stack environment build:
local stackpath = "/Users/username/spack-stack/spack-stack-1.8.0/envs/ufs-srw-env"
local modulepath = stackpath .. "/install/modulefiles/Core"
prepend_path("MODULEPATH", modulepath)

stack_gnu_ver=os.getenv("stack_apple_clang_ver") or "15.0.0"
load(pathJoin("stack-apple-clang", stack_gnu_ver))

stack_openmpi_ver=os.getenv("stack_openmpi_ver") or "5.0.3"
load(pathJoin("stack-openmpi", stack_openmpi_ver))

cmake_ver=os.getenv("cmake_ver") or "3.27.9"
load(pathJoin("cmake", cmake_ver))

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


local libjpeg_ROOT = os.getenv("libjpeg_turbo_ROOT")
local jasper_ROOT = os.getenv("jasper_ROOT")
local libpng_ROOT = os.getenv("libpng_ROOT")
local ldflags0 = os.getenv("LDFLAGS") or ""

if jasper_ROOT and libpng_ROOT and libjpeg_ROOT then
   local ldflags1 = " -L" .. libjpeg_ROOT .. "/lib -ljpeg -Wl,-rpath," .. libjpeg_ROOT .. "/lib"
   local ldflags2 = " -L" .. jasper_ROOT .. "/lib -ljasper -Wl,-rpath," .. jasper_ROOT .. "/lib"
   local ldflags3 = " -L" .. libpng_ROOT .. "/lib -lpng -Wl,-rpath," .. libpng_ROOT .. "/lib"
   local ldflags =  ldflags0 .. ldflags1 .. ldflags2 .. ldflags3
   setenv("LDFLAGS", ldflags)
end
