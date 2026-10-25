// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick
import "Layouts.js" as Layouts
Item {
 id: board
 required property var controller
 property real keyScale: controller.keyScale
 readonly property real gap: 5
 property bool allowShortcuts: true
 property bool shift: false
 property bool caps: false
 property bool ctrl: false
 property bool alt: false
 property bool altgr: false
 property real rowHeight: (height - 44 - gap * 5) / 5
 function reset() { shift=false; caps=false; ctrl=false; alt=false; altgr=false; }
 function label(k) { return k.kind === "key" && Layouts.printable(k) ? Layouts.text(k,shift,caps,altgr) : k.label; }
 function active(k) { return k.kind !== "key" && board[k.kind]; }
 function send(k) {
  if (!allowShortcuts && ["ctrl","alt"].includes(k.kind)) return;
  if (k.kind !== "key") { board[k.kind]=!board[k.kind]; return; }
  var upper=!altgr && (Layouts.printable(k) && /^[a-zñ]$/.test(k.label) ? shift !== caps : shift);
  var mask=(upper?1:0)|(ctrl?4:0)|(alt?8:0)|(altgr && k.alt!==k.label?128:0);
  controller.send({action:"tap",code:k.code,text:Layouts.text(k,shift,caps,altgr),modifiers:mask,
    dead:k.code===26 ? (shift||altgr ? "dead_diaeresis":"dead_acute") : ""});
  shift=false;
 }
 function snapshot() {
  var result=[];
  for (var r=0;r<lines.count;++r) {
   var row=lines.itemAt(r);
   for (var c=0;c<row.keys.count;++c) {
    var item=row.keys.itemAt(c); var p=item.mapToItem(board,0,0);
    result.push({code:item.modelData.code,kind:item.modelData.kind,label:item.title,x:p.x,y:p.y,width:item.width,height:item.height});
   }
  }
  return result;
 }
 Rectangle {
  width:parent.width; height:38; color:"transparent"
  Text { anchors.left:parent.left; anchors.verticalCenter:parent.verticalCenter
   text:controller.error || ("Español · "+(controller.ready?"Listo":"Conectando…"))
   color:controller.error?"#ed8796":"#cad3f5"; font.pixelSize:13; width:parent.width-(controller.ready?190:290); elide:Text.ElideRight }
  Row {
   anchors.right:parent.right; spacing:6
   Repeater {
    model:controller.ready?["−","+","Ocultar"]:["Reintentar","−","+","Ocultar"]
    delegate:Rectangle {
     required property string modelData
     width:modelData==="Reintentar"?100:modelData==="Ocultar"?85:34; height:34; radius:8; color:"#494d64"
     Text { anchors.centerIn:parent; text:modelData; color:"#cad3f5"; font.pixelSize:15 }
     MouseArea { anchors.fill:parent; onClicked: {
      if (modelData==="Reintentar") controller.retry();
      else if (modelData==="Ocultar") controller.hide();
      else controller.keyScale=Math.max(0.75,Math.min(1.25,controller.keyScale+(modelData==="+"?0.1:-0.1)));
     } }
    }
   }
  }
 }
 Column {
  y:44; spacing:board.gap; width:parent.width
  Repeater {
   id:lines; model:Layouts.rows
   delegate:Row {
    id:row
    required property var modelData
    property alias keys:buttons
    readonly property real units:modelData.reduce((sum,k)=>sum+k.units,0)
    width:board.width; spacing:board.gap
    Repeater {
     id:buttons; model:row.modelData
     delegate:Rectangle {
      required property var modelData
      readonly property string title:board.label(modelData)
      width:(board.width-board.gap*(row.modelData.length-1))*modelData.units/row.units
      height:board.rowHeight; radius:8
      color:mouse.pressed||board.active(modelData)?"#8aadf4":"#363a4f"
      opacity:(!board.allowShortcuts && ["ctrl","alt"].includes(modelData.kind))?0.25:(controller.ready||modelData.kind!=="key"?1:0.45)
      Text { anchors.centerIn:parent; text:title; font.family:"Roboto"; font.pixelSize:18*board.keyScale; color:"#cad3f5" }
      MouseArea {
       id:mouse; anchors.fill:parent; enabled:(board.allowShortcuts || !["ctrl","alt"].includes(modelData.kind)) && (controller.ready||modelData.kind!=="key")
       onPressed: { board.send(modelData); if ([14,105,106,108,103,111].includes(modelData.code)) repeatDelay.start(); }
       onReleased: { repeatDelay.stop(); repeatKey.stop(); }
       onCanceled: { repeatDelay.stop(); repeatKey.stop(); }
      }
      Timer { id:repeatDelay; interval:420; onTriggered:repeatKey.start() }
      Timer { id:repeatKey; interval:85; repeat:true; onTriggered: { if (mouse.pressed) board.send(modelData); else stop(); } }
     }
    }
   }
  }
 }
}
