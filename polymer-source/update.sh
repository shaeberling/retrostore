#!/bin/bash

SCRIPT_LOCATION="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# Ensure that the Bower components have been installed.
if [ ! -d "${SCRIPT_LOCATION}/bower_components" ]; then
  echo "Bower components not present. Installing ..."
  bower install
else
  echo "Bower components present."
fi

pushd "${SCRIPT_LOCATION}"
polymer build --bundle --js-minify --css-minify --html-minify
popd

POLYMER_DEST="${SCRIPT_LOCATION}/../appengine/src/main/webapp/WEB-INF/polymer-app/"

if [ -d "${POLYMER_DEST}" ]; then
  echo "Deleting destination..."
  rm -r "${POLYMER_DEST}"/*
else
  mkdir -p "${POLYMER_DEST}"
fi
cp -R "${SCRIPT_LOCATION}"/build/default/* "${POLYMER_DEST}"

