<html>
<head>
    <title>RetroStore - Report app</title>
    <link href="https://fonts.googleapis.com/css?family=Roboto" rel="stylesheet">
    <style>
        body {
         background: #f2f1ec;
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
        #logo {
        	height: 50px;
        	float: right
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
<h1><img id="logo" src="https://github.com/shaeberling/retrostore/raw/master/docs/retrostore_logo.png" />Report an app</h1>
<div id="inner-content">
	<form action="/reportapp" method="post">
		<p>Use this form to report an app. Please let us know why you are reporting it and we will look into it as quickly as we can.</p>
		<p>The app you are going to report is:</p>

	<div class="card">
		<img class="app-icon" src="<!--RS screenshotUrl RS-->">
		<div id="title"><!--RS appTitle RS--></div>

		<div id="input-area">
		<div class="label">Your name</div>
		<input name="reporter_name" />
		<div class="label">Your e-mail address</div>
		<input name="reporter_email" type="email"/>
		<div class="label">Your message</div>
		<textarea name="message" rows="10"></textarea>
		<input type="submit"/>
		</div>
	</div>
	<input type="hidden" name="appId" value="<!--RS appId RS-->" />
	</form>
</div>
</div>
</body>
</html>