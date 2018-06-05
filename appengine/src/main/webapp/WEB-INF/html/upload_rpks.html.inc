

<html>
<head>
    <title>RetroStore - Upload RPKs</title>
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
    </a>Upload RPK packages</h1>
<div id="inner-content">
	<p>
		Try to keep the number of items to 5-10 since otherwise a timeout might occur.
	</p>
	<form action="/import" method="post" enctype="multipart/form-data">
    Select RPKs: <input type="file" name="rpk" multiple/>
    <input type="submit"/>
	</form>

</div>
</div>
</body>
</html>
