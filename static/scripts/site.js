var colorhex = "#FF0000";
var color = "#FF0000";
//var colorObj = w3color(color);

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
function campaignChange(){
  var ev = event.target;
  jsn = {campaign_id:ev.value}
  // console.log(JSON.stringify(jsn))
  saveCampaignChange(JSON.stringify(jsn))
}      
function saveCampaignChange(json) {
  fetch('/api/campaignSelect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: json
  }).then(() => {
    location.reload();
  }).catch(error => {
    console.error('Error:', error);
  });
}

function sceneFilterChange(){
  var ev = event.target;
  jsn = {scene_id:ev.value}
  // console.log(JSON.stringify(jsn))
  saveSceneFilter(JSON.stringify(jsn))
} 

function saveSceneFilter(json) {
  fetch('/api/sceneFilter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: json
  }).then(() => {
    location.reload();
  }).catch(error => {
    console.error('Error:', error);
  });
}


function volumeChange(){
  const slideClick = function(volume){
      fetch("/set_volume", {
          method: "POST",
          body: JSON.stringify({ volume }),
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  const slider = document.getElementById("volume_slider");
  const volume = slider.value;
  const vElement = document.getElementById("volume");
  vElement.textContent = "Master Volume: " + volume;
  slideClick(volume)
}

function nextSong(){

  const Click = function(){
      fetch("/nextsong", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)//.then(() => window.location.reload());
}

function songAndVideoCount(){
  const Click = function(){
      fetch("/api/songandvideocount", {
          method: "GET",
          headers: {
          "Content-Type": "application/json" 
      }
      })
      .then(response => response.text())
      .then(data => {
         const dataObj = JSON.parse(data);
         //console.log(dataObj);
         document.getElementById("songQueueCount").textContent =  "Songs: " + dataObj[0].songQCnt || 0;
         document.getElementById("videoQueueCount").textContent = "Video: " + dataObj[1].videoQCnt || 0;
       });
  }
  Click()
}

function nextVideo(){

  const Click = function(){
      fetch("/nextvideo", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)//.then(() => window.location.reload());
}

function killQueue(){

  const Click = function(){
      fetch("/killqueue", {
          method: "POST",
          body: "",
          headers: {
          "Content-Type": "application/json" 
      }
      }).then(response => response.text()).then(data => console.log(data));
  }
  const Click2 = function(){
    fetch("/activatescenes/?id=-1", {
        method: "POST",
        body: "",
        headers: {
        "Content-Type": "application/json" 
    }
    }).then(response => response.text()).then(data => console.log(data));
  }
  Click()
  sleep(2000)
  Click2()
  //sleep(2000).then(() => window.location.reload());
}

function mouseOverColor(hex) {
    document.getElementById("divpreview").style.visibility = "visible";
    document.getElementById("divpreview").style.backgroundColor = hex;
    document.body.style.cursor = "pointer";
}
function mouseOutMap() {
    if (hh == 0) {
        document.getElementById("divpreview").style.visibility = "hidden";
    } else {
      hh = 0;
    }
    document.getElementById("divpreview").style.backgroundColor = colorObj.toHexString();
    document.body.style.cursor = "";
}
var hh = 0;

function componentToHex(c) {
  var hex = Number(c).toString(16).toUpperCase();
  return hex.length == 1 ? "0" + hex : hex;
}

function rgbToHex(r, g, b) {
  return "#" + componentToHex(r) + componentToHex(g) + componentToHex(b);
}

function hexToRGB(hexColor){
  return {
    red: (hexColor >> 16) & 0xFF,
    green: (hexColor >> 8) & 0xFF,  
    blue: hexColor & 0xFF,
  }
}

var RGBvalues = (function() {

var _hex2dec = function(v) {
    return parseInt(v, 16)
};

var _splitHEX = function(hex) {
    var c;
    if (hex.length === 4) {
        c = (hex.replace('#','')).split('');
        return {
            r: _hex2dec((c[0] + c[0])),
            g: _hex2dec((c[1] + c[1])),
            b: _hex2dec((c[2] + c[2]))
        };
    } else {
         return {
            r: _hex2dec(hex.slice(1,3)),
            g: _hex2dec(hex.slice(3,5)),
            b: _hex2dec(hex.slice(5))
        };
    }
};

var _splitRGB = function(rgb) {
    var c = (rgb.slice(rgb.indexOf('(')+1, rgb.indexOf(')'))).split(',');
    var flag = false, obj;
    c = c.map(function(n,i) {
        return (i !== 3) ? parseInt(n, 10) : flag = true, parseFloat(n);
    });
    obj = {
        r: c[0],
        g: c[1],
        b: c[2]
    };
    if (flag) obj.a = c[3];
    return obj;
};

var color = function(col) {
    var slc = col.slice(0,1);
    if (slc === '#') {
        return _splitHEX(col);
    } else if (slc.toLowerCase() === 'r') {
        return _splitRGB(col);
    } else {
        console.log('!Ooops! RGBvalues.color('+col+') : HEX, RGB, or RGBa strings only');
    }
};

return {
    color: color
};
}());



function clickColor(hex, seltop, selleft, html5, field = '') {
    var elnt = event.target;
    console.log(elnt.id)
    //elnt
    var c, cObj, colormap, areas, i, areacolor, cc;
    if (html5 && html5 == 5)  {
        c = document.getElementById(elnt.id).value;
    } else {
        if (hex == 0)  {
            c = document.getElementById(elnt.id).value;
            c = c.replace(/;/g, ","); //replace any semicolon with a comma
        } else {
            c = hex;
        }
    }
    cObj = w3color(c);
    colorhex = cObj.toHexString();
    if (cObj.valid) {
        clearWrongInput();
    } else {
        wrongInput();
        return;
    }
    r = cObj.red;
    g = cObj.green;
    b = cObj.blue;
    id = elnt.id.split("_ID_")
    //console.log(elnt)
    rgbsave = "[" + r.toString() + "," + g.toString() + "," + b.toString() + "]"
    if(field == 'color'){
      jsn = {scenePattern_ID:id[1],color:rgbsave}
    }
    if(field == 'cdiff'){
      jsn = {scenePattern_ID:id[1],cdiff:rgbsave}
    }
    if(field == 'color1'){
      jsn = {wledPattern_ID:id[1],color1:rgbsave}
    }
    if(field == 'color2'){
      jsn = {wledPattern_ID:id[1],color2:rgbsave}
    }
    if(field == 'color3'){
      jsn = {wledPattern_ID:id[1],color3:rgbsave}
    }
    //console.log(JSON.stringify(jsn))
    
    console.log(JSON.stringify(jsn));
    saveChange(JSON.stringify(jsn))
    //document.getElementById("colornamDIV").innerHTML = (cObj.toName() || "");
    //document.getElementById("colorhexDIV").innerHTML = cObj.toHexString();
    //document.getElementById("colorrgbDIV").innerHTML = cObj.toRgbString();
    //document.getElementById("colorhslDIV").innerHTML = cObj.toHslString();    
/*     if ((!seltop || seltop == -1) && (!selleft || selleft == -1)) {
        colormap = document.getElementById("colormap");
        areas = colormap.getElementsByTagName("AREA");
        for (i = 0; i < areas.length; i++) {
            areacolor = areas[i].getAttribute("onmouseover").replace('mouseOverColor("', '');
            areacolor = areacolor.replace('")', '');
            if (areacolor.toLowerCase() == colorhex) {
                cc = areas[i].getAttribute("onclick").replace(')', '').split(",");
                seltop = Number(cc[1]);
                selleft = Number(cc[2]);
            }
        }
    } */

/*     if ((seltop+200)>-1 && selleft>-1) {
        document.getElementById("selectedhexagon").style.top=seltop + "px";
        document.getElementById("selectedhexagon").style.left=selleft + "px";
        document.getElementById("selectedhexagon").style.visibility="visible";
  } else {
        document.getElementById("divpreview").style.backgroundColor = cObj.toHexString();
        document.getElementById("selectedhexagon").style.visibility = "hidden";
  } */
    //document.getElementById("selectedcolor").style.backgroundColor = cObj.toHexString();
    //document.getElementById("html5colorpicker").value = cObj.toHexString();  
  //ocument.getElementById('slideRed').value = r;
  //document.getElementById('slideGreen').value = g;
  //document.getElementById('slideBlue').value = b;
  //changeRed(r);changeGreen(g);changeBlue(b);
  //changeColor();
  //document.getElementById("fixed").style.backgroundColor = cObj.toHexString();
}
function wrongInput() {
    document.getElementById("entercolorDIV").className = "has-error";
    document.getElementById("wronginputDIV").style.display = "block";
}
function clearWrongInput() {
    /* document.getElementById("entercolorDIV").className = "";
    docume nt.getElementById("wronginputDIV").style.display = "none"; */
}
function changeRed(value) {
    document.getElementById('valRed').innerHTML = value;
    changeAll();
}
function changeGreen(value) {
    document.getElementById('valGreen').innerHTML = value;
    changeAll();
}
function changeBlue(value) {
    document.getElementById('valBlue').innerHTML = value;
    changeAll();
}
function changeAll() {
    var r = document.getElementById('valRed').innerHTML;
    var g = document.getElementById('valGreen').innerHTML;
    var b = document.getElementById('valBlue').innerHTML;
    document.getElementById('change').style.backgroundColor = "rgb(" + r + "," + g + "," + b + ")";
    document.getElementById('changetxt').innerHTML = "rgb(" + r + ", " + g + ", " + b + ")";
    document.getElementById('changetxthex').innerHTML = w3color("rgb(" + r + "," + g + "," + b + ")").toHexString();
}

function hslLum_top() {
  var i, a, match;
  var color = document.getElementById("colorhexDIV").innerHTML;
  var hslObj = w3color(color);
  var h = hslObj.hue;
  var s = hslObj.sat;
  var l = hslObj.lightness;
  var arr = [];
  for (i = 0; i <= 20; i++) {
      arr.push(w3color("hsl(" + h + "," + s + "," + (i * 0.05) + ")"));
  }
  arr.reverse();
  a = "<h3 class='w3-center'>Lighter / Darker:</h3><table class='colorTable' style='width:100%;'>";
  match = 0;
  for (i = 0; i < arr.length; i++) {
    if (match == 0 && Math.round(l * 100) == Math.round(arr[i].lightness * 100)) {
      a += "<tr><td></td><td></td><td></td></tr>";
      a += "<tr>";
      a += "<td style='text-align:right;'><b>" + Math.round(l * 100) + "%&nbsp;</b></td>";
      a += "<td style='background-color:" + w3color(hslObj).toHexString() + "'><br><br></td>";
      a += "<td>&nbsp;<b>" + w3color(hslObj).toHexString() + "</b></td>";
      a += "</tr>";
      a += "<tr><td></td><td></td><td></td></tr>";
      match = 1;      
    } else {
      if (match == 0 && l > arr[i].lightness) {
        a += "<tr><td></td><td></td><td></td></tr>";
        a += "<tr>";
        a += "<td style='text-align:right;'><b>" + Math.round(l * 100) + "%&nbsp;</b></td>";
        a += "<td style='background-color:" + w3color(hslObj).toHexString() + "'></td>";
        a += "<td>&nbsp;<b>" + w3color(hslObj).toHexString() + "</b></td>";
        a += "</tr>";
        a += "<tr><td></td><td></td><td></td></tr>";
        match = 1;
      }
      a += "<tr>";
      a += "<td style='width:40px;text-align:right;'>" + Math.round(arr[i].lightness * 100) + "%&nbsp;</td>";
      a += "<td style='cursor:pointer;background-color:" + arr[i].toHexString() + "' onclick='clickColor(\"" + arr[i].toHexString() + "\")'></td>";
      a += "<td style='width:80px;'>&nbsp;" + arr[i].toHexString() + "</td>";
      a += "</tr>";
    }
  }
  a += "</table>";
  document.getElementById("lumtopcontainer").innerHTML = a;
}

function hslTable(x) {
  var lineno, header, i, a, match, same, comp, loopHSL, HSL;
  var color = document.getElementById("colorhexDIV").innerHTML;
  var hslObj = w3color(color);
  var h = hslObj.hue;
  var s = hslObj.sat;
  var l = hslObj.lightness;
  var arr = [];
  if (x == "hue") {header = "Hue"; lineno = 24;}
  if (x == "sat") {header = "Saturation"; lineno = 20;}
  if (x == "light") {header = "Lightness"; lineno = 20;}  
  for (i = 0; i <= lineno; i++) {
    if (x == "hue") {arr.push(w3color("hsl(" + (i * 15) + "," + s + "," + l + ")"));}
    if (x == "sat") {arr.push(w3color("hsl(" + h + "," + (i * 0.05) + "," + l + ")"));}
    if (x == "light") {arr.push(w3color("hsl(" + h + "," + s + "," + (i * 0.05) + ")"));}
  }
  if (x == "sat" || x == "light") {arr.reverse();}
  a = "<h3>" + header + "</h3>";
  a += "<div class='w3-responsive'>";
  a += "<table class='ws-table-all colorTable' style='width:100%;white-space: nowrap;font-size:14px;'>";
  a += "<tr>";
  a += "<td style='width:150px;'></td>";
  a += "<td style='text-align:right;text-transform:capitalize;'>" + x + "&nbsp;</td>";
  a += "<td>Hex</td>";
  a += "<td>Rgb</td>";
  a += "<td>Hsl</td>";
  a += "</tr>";  
  match = 0;
  for (i = 0; i < arr.length; i++) {
    same = 0;
    if (x == "hue") {
      loopHSL = w3color(arr[i]).hue;
      HSL = h;
      if (i == arr.length - 1) {loopHSL = 360;}
      comp = (loopHSL > HSL);
    }
    if (x == "sat") {
      loopHSL = Math.round(w3color(arr[i]).sat * 100);
      HSL = Number(s * 100);
      HSL = Math.round(HSL);
      comp = (loopHSL < HSL);
      HSL = HSL + "%";
      loopHSL = loopHSL + "%";
    }
    if (x == "light") {
      loopHSL = Math.round(w3color(arr[i]).lightness * 100);
      HSL = Number(l * 100);
      HSL = Math.round(HSL);      
      comp = (loopHSL < HSL);
      HSL = HSL + "%";
      loopHSL = loopHSL + "%";
    }
    if (HSL == loopHSL) {
      match++;
      same = 1;
    }
    if (comp) {match++;}
    if (match == 1) {
      a += "<tr class='ws-green'>";
      a += "<td style='background-color:" + hslObj.toHexString() + "'></td>";
      a += "<td style='text-align:right;'><b>" + HSL + "&nbsp;</b></td>";
      a += "<td><b>" + hslObj.toHexString() + "</b></td>";
      a += "<td><b>" + hslObj.toRgbString() + "</b></td>";
      a += "<td><b>" + hslObj.toHslString() + "</b></td>";
      a += "</tr>";
      match = 2;
    }
    if (same == 0) {
      a += "<tr>";
      a += "<td style='cursor:pointer;background-color:" + arr[i].toHexString() + "' onclick='clickColor(\"" + arr[i].toHexString() + "\")'></td>";
      a += "<td style='text-align:right;'>" + loopHSL + "&nbsp;</td>";
      a += "<td>" + arr[i].toHexString() + "</td>";
      a += "<td>" + arr[i].toRgbString() + "</td>";
      a += "<td>" + arr[i].toHslString() + "</td>";
      a += "</tr>";
    }
  }
  a += "</table></div>";
  if (x == "hue") {document.getElementById("huecontainer").innerHTML = a;}
  if (x == "sat") {document.getElementById("hslsatcontainer").innerHTML = a;}
  if (x == "light") {document.getElementById("hsllumcontainer").innerHTML = a;}

}
function changeColor(value) {
  hslLum_top();  
  hslTable("hue");
  hslTable("sat");
  hslTable("light");
}
window.onload = function() {
    var x = document.createElement("input");
    x.setAttribute("type", "color");
    if (x.type == "text") {
        document.getElementById("html5DIV").style.visibility = "hidden";
    }
}
function submitOnEnter(e) {
    keyboardKey = e.which || e.keyCode;
    if (keyboardKey == 13) {
        clickColor(0,-1,-1);
    }
}


function videoStartStop() {
  const button = document.getElementById("playPauseButton");

  // Make the API call to toggle video play/pause
  fetch('/video_stopstart', {
    method: 'POST',
  })
  .then(response => response.json())
  .then(result => {
    console.log('Start/stop request successful:', result);

    // Toggle the button's value based on the current state
    if (button.value === "||") {
      button.value = "▶"; // Change to play icon
    } else {
      button.value = "||"; // Change to pause icon
    }
  })
  .catch(error => console.error('Error in start/stop request:', error));
}

function videoSeek(value) {
  fetch('/video_seek', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: value })
  })
  .then(response => response.json())
  .then(result => {
    console.log('Seek request successful:', result);
  })
  .catch(error => console.error('Error in seek request:', error));
}