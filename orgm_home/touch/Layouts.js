// SPDX-License-Identifier: GPL-3.0-or-later
// Independent Latin American adaptation of end-4 OSK; see UPSTREAM.md.
function key(code, label, shifted, alt, width, kind) {
 return {code, label, shifted: shifted || label, alt: alt || label, units: width || 1, kind: kind || "key"};
}
var rows = [
 [key(1,"Esc"),key(2,"1","!","|"),key(3,"2","\"","@"),key(4,"3","#"),key(5,"4","$","~"),key(6,"5","%"),key(7,"6","&"),key(8,"7","/","{"),key(9,"8","(","["),key(10,"9",")","]"),key(11,"0","=","}"),key(12,"'","?","\\"),key(13,"¿","¡"),key(14,"⌫",null,null,1.7)],
 [key(15,"Tab",null,null,1.3),key(16,"q","Q"),key(17,"w","W"),key(18,"e","E","€"),key(19,"r","R"),key(20,"t","T"),key(21,"y","Y"),key(22,"u","U"),key(23,"i","I"),key(24,"o","O"),key(25,"p","P"),key(26,"´","¨","¨"),key(27,"+","*","~"),key(28,"Enter",null,null,1.6)],
 [key(-1,"Caps",null,null,1.6,"caps"),key(30,"a","A"),key(31,"s","S"),key(32,"d","D"),key(33,"f","F"),key(34,"g","G"),key(35,"h","H"),key(36,"j","J"),key(37,"k","K"),key(38,"l","L"),key(39,"ñ","Ñ","~"),key(40,"{","["),key(43,"}","]")],
 [key(-1,"Shift",null,null,1.9,"shift"),key(86,"<",">","\\"),key(44,"z","Z"),key(45,"x","X"),key(46,"c","C"),key(47,"v","V"),key(48,"b","B"),key(49,"n","N"),key(50,"m","M"),key(51,",",";"),key(52,".",":"),key(53,"-","_"),key(103,"↑")],
 [key(-1,"Ctrl",null,null,1.4,"ctrl"),key(-1,"Alt",null,null,1.3,"alt"),key(-1,"AltGr",null,null,1.5,"altgr"),key(57,"Espacio"," "," ",6),key(105,"←"),key(108,"↓"),key(106,"→"),key(111,"Supr",null,null,1.3)]
];
function printable(k) {
 if ([1,14,15,28,103,105,106,108,111].includes(k.code)) return false;
 return k.label.length === 1 || k.code === 57;
}
function text(k, shift, caps, altgr) {
 if (k.code === 57) return " ";
 if (!printable(k)) return "";
 if (altgr) return k.alt;
 if (/^[a-zñ]$/.test(k.label)) return shift !== caps ? k.shifted : k.label;
 return shift ? k.shifted : k.label;
}
