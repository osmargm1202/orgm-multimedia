"""Text using the existing persistent Latin American keyboard, without re-keymaps."""
import json
from pathlib import Path
import re
import unicodedata

# Read the same fixed key definitions used by the laptop's native keyboard.
_LAYOUT=(Path(__file__).with_name('touch')/'Layouts.js').read_text()
_PATTERN=r'key\((\d+),("(?:\\.|[^"\\])*")(?:,("(?:\\.|[^"\\])*"))?(?:,("(?:\\.|[^"\\])*"))?'
_KEYS={' ':(57,0)}
for match in re.finditer(_PATTERN,_LAYOUT):
    code=int(match[1])
    if code in {1,14,15,26,28,103,105,106,108,111}:continue
    for literal,mask in zip(match.groups()[1:],[0,1,128]):
        if literal:
            value=json.loads(literal)
            if len(value)==1:_KEYS.setdefault(value,(code,mask))


def encode_text(value):
    result=[]
    for char in value:
        if char in _KEYS:
            result.append(_KEYS[char]);continue
        parts=unicodedata.normalize('NFD',char)
        if len(parts)==2 and parts[0] in _KEYS and parts[1] in {'\u0301','\u0308'}:
            result.extend([(26,0 if parts[1]=='\u0301' else 1),_KEYS[parts[0]]])
        else:
            raise ValueError('Text cannot be typed with this native keyboard')
    return result
