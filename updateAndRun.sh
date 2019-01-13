#!/bin/bash

cd polymer-source
./update.sh
cd -
./gradlew appengineRun

