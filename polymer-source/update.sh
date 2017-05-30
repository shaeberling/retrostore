#!/bin/sh

polymer build --bundle --js-minify --css-minify --html-minify

rm -r ../appengine/src/main/webapp/WEB-INF/polymer-app/*
cp -R build/default/* ../appengine/src/main/webapp/WEB-INF/polymer-app/

