
retrostore = {};

retrostore.rpc = function(method, payload, cb) {
  var xmlhttp = new XMLHttpRequest();
  xmlhttp.onreadystatechange = function() {
    if (xmlhttp.readyState != 4) {
      return;
    }
    if (xmlhttp.status == 200) {
      cb(JSON.parse(xmlhttp.responseText));
    } else {
      console.log("Request failed");
      cb(null);
    }
  };
  xmlhttp.open("GET", "/rpc?m=" + method, true);
  xmlhttp.send(JSON.stringify(payload));
};

console.log("Retrostore JS code loaded...");