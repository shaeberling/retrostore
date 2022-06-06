<img src="https://github.com/shaeberling/retrostore/raw/master/docs/retrostore_logo.png" width="300">

![workflow status](https://github.com/shaeberling/retrostore/actions/workflows/gradle.yml/badge.svg)

**RetroStore** aims to be an app store that is home to often long forgotten games and apps on platforms from our past.

Take e.g. a system like the [TRS-80](https://en.wikipedia.org/wiki/TRS-80). There are many games and apps that have been
developed for it but are hard to come by nowadays. Often there is no commercial interest anymore from the original
authors. 

However, there are often vibrant communities about these old platforms and emulators that try to keep the history alive.
While these emulators ([like this one for Android](https://github.com/apuder/TRS-80)) are doing a fantastic job, they
suffer from the absence of easy to obtain and install app images.

This is where **RetroStore** comes in. It aims to provide an open platform to store and distribute these old gems. It
does so by offering forms to upload old application images, and and API for accessing them. The APIs can be used by
emulators to easily add these titles to their applications.

For now we aim to only support application without commercial interest. Should there be desire to at some point have
authors sell games and apps for these old platforms, we would rethink this model and add an incentive model.

Initial platform will be the TRS-80. If you are an emulator developer for this or another platform, feel free to reach
out so we can expand support.

Contact: info@retrostore.org

# RetroStore SDK

If you are looking to integrate RetroStore into your client (be it a software emulator or a hardware project), then you should head over to the [RetroStore SDK repository](https://github.com/shaeberling/retrostore-sdk).


# Contributor Notes

The following instructions are for developers that want to contribute to the RetroStore codebase.

## Install tools

In order to work on and make changes to the user interface, polymer-cli, npm and bower are
required. THe developer portal is using Polymer 2.0, so follow the instructions to install
these tools on the (Polymer website)[https://polymer-library.polymer-project.org/2.0/docs/install-2-0].

## Start a local server

A local server will not have all the features of a full AppEngine environment, but you can
test most things like this without the need to deploy it, which is nice.

A convenience script is available that will compile the Polymer frontend code and then start
up an AppEngine development server. It's in the root of the reposiory:

```
./updateAndRun.sh
```

If you do not work on the GUI part and you do not want to install Polymer and Bower, you can
simply run the AppEngine development server without rebuilding the GUI parts. Since a
current build is in the repository, you can simply run this:

```
./gradlew appengineRun
``` 

In both cases, the server is available at `http://localhost:8888`. To access the developer
portal, browse to `http://localhost:8888/app-management-view`.

## Frontend work

The frontend consists of two parts: The main homepage that users see when they browse
to retrostore.org for one, and then the developer backend application that is used to
upload new applications, edit existing ones, manage disk images, store listing and screenshots.

### Changing the homepage
The main website is easy to change. Simply edit the code under `appengine\src\main\webapp\WEB-INF\public`.
It is not necessary to build this part in any way, it gets served directly to the users.

### Changing developer portal
The developer portal is a web application that is built with Polymer. Head over to the
(Polymer website)[https://www.polymer-project.org/] to see how it works and run through tutorials
if you need to.

If you have both polymer-cli and bower installed (see above) then you are ready to go. You can
work on the code in two ways: Build it every time or run a special developer mode we built for
the RetroStore backend.

To rebuild and run a local server, simply run:

```
./updateAndRun.sh
```

This will rebuilt the Polymer app and then launch a local developer server. You should run this
before deploying a new version, since it is exactly what you would deploy to the servers.

However, if you make a lot of changes, it can be tedious to rebuild and restart all the time.
For this use case a special developer mode is supported. All you have to do is start up a local
polymer development server by going to the source directory:

```
cd polymer-source
polymer server
```

This will launch a local server which reacts to code changes right away. Once it is running,
a local RetroStore development server will automatically connect to the polymer developer server
by making requests to it to serve the developer portal. So just run `./updateAndRun.sh` in 
a seperate terminal while the polymer server is running, and you are good to go. All changes
you make to the Polymer application will be shown when you refresh the page.


