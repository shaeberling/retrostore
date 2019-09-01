

<!--
  ~  Copyright 2018, Sascha Häberling
  ~
  ~  Licensed under the Apache License, Version 2.0 (the "License");
  ~  you may not use this file except in compliance with the License.
  ~  You may obtain a copy of the License at
  ~
  ~         http://www.apache.org/licenses/LICENSE-2.0
  ~
  ~  Unless required by applicable law or agreed to in writing, software
  ~  distributed under the License is distributed on an "AS IS" BASIS,
  ~  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  ~  See the License for the specific language governing permissions and
  ~  limitations under the License.
  -->

<html>
<head>
    <title>Firmware Management</title>
    <link href="https://fonts.googleapis.com/css?family=Roboto" rel="stylesheet">
    <style>
        body {
         background:#eee;
         background: radial-gradient(circle, rgba(151,104,184,1) 0%, rgba(255,143,143,1) 50%, rgba(255,181,78,1) 100%);
         font-family: 'Roboto', sans-serif;
        }
        h1 {
        	margin-top: 0;
        }
	    input, textarea {
        	width: 25em;
        	margin-bottom: 1em;
        	font-size: 1.1em;
        	border-radius: 0.2em;
        	border: 2px solid gray;
        	padding: 0.2em;
        	display: block;
        }

        #content {
        	max-width: 600px;
        	background: rgba(0, 0, 0, 0.25);
        	margin: auto;
        	display: block;
        	padding: 2em;
        	border-radius: 1em;
        }
        #inner-content {
        	background: rgba(255, 255, 255, 0.5);
        	padding: 1em;
        	border-radius: 0.5em;
        }
        #title {
        	font-weight: bold;
        	font-size: 130%;
        }
        #logo img {
        	height: 50px;
		}
        #logo {
        	float: right;
        }
        #input-area {
        	margin-top: 3em;
        }
        .card {
        	margin: auto;
        }
        .card img {
        	width: 20em;
        }
    </style>
</head>
<body>
<div id="content">
    <h1><a id="logo" href="/">
        <img src="https://github.com/shaeberling/retrostore/raw/master/docs/retrostore_logo.png" />
    </a><!--PRODUCT--> Firmware</h1>
    <div id="inner-content">
        <p>
            Choose a RetroStore Card revision for which to upload new firmware. Versions will automatically be incremented.
        </p>
        <form action="/card" method="post" enctype="multipart/form-data">
            <p>Revision:
            <select name="revision">
                <option value="1" selected>1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4">4</option>
                <option value="5">5</option>
            </select></p>
            Select firmware file: <input type="file" name="firmware" />
            <input type="submit"/>
        </form>

    </div>
</div>
</body>
</html>
