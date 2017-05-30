#!/bin/sh

cd polymer-source
./update.sh
cd -
./gradlew appengineRun

