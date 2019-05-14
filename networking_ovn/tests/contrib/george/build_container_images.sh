#!/usr/bin/env bash

# The directory structure is as follows:
# networking_ovn/tests/contrib/george/build_container_images.sh
NETWORKING_OVN_DIR=$(dirname $(dirname $(dirname $(dirname $(dirname $(realpath $0))))))
CONTRIB_DIR=${CONTAINER_IMAGES_DIR:-$NETWORKING_OVN_DIR/networking_ovn/tests/contrib/george}
DOCKERFILE_SUFFIX=.Dockerfile

BUILD_IMAGE_ERROR=1


function build_image() {
    local container_name=$1
    local Dockerfile=$2

    sudo buildah bud -t $container_name -f $Dockerfile .
    if [ $? -ne 0 ]; then
        echo "Building an image $container_name failed!" 1>&2
        exit $BUILD_IMAGE_ERROR
    fi
}


function patch_image() {
    local container_name=$1
    local Dockerfile=$2
    working_cont=$(sudo buildah from $container_name)
    working_dir=$(sudo buildah mount $working_cont)

    pushd $working_dir && rm -rf networking_ovn && cp -r $NETWORKING_OVN_DIR . && popd

    sudo buildah umount $working_cont
}


function main() {
    pushd $CONTRIB_DIR
    for Dockerfile in $(ls containers/*/*$DOCKERFILE_SUFFIX); do
        echo "Building an image from file $Dockerfile"
        name=$(basename -s $DOCKERFILE_SUFFIX $Dockerfile)
        if sudo podman images | grep -q $name; then
            echo "Image $name $Dockerfile exists"
            #patch_image $name $Dockerfile
        else
            build_image $name $Dockerfile
        fi
    done
    popd
}

main
