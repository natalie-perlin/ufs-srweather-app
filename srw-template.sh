#!/bin/bash
export SINGULARITYENV_FI_PROVIDER=tcp
#export SINGULARITY_SHELL=/bin/bash
export SINGULARITY_SHELL= /usr/share/lmod/lmod/init/bash
export SINGULARITYENV_PREPEND_PATH="/home/ubuntu/ufs-srweather-app/bin"
img="/home/ubuntu/ubuntu20.04-intel-srwapp-v2.2.0.img"
cmd=$(basename "$0")
arg="$@"
echo running: singularity exec "${img}" $cmd $arg
/usr/local/bin/singularity exec -B /home -B /scratch "${img}" $cmd $arg
