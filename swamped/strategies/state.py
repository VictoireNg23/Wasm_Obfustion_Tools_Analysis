PERTURBED_OFFSET = list()
#Need update
PERTURBED_INFO = list()
import numpy as np
import random as _stdlib_random
import time
from scipy.stats import beta
from wasmParser import sectionStructure as ss

import sys
from pathlib import Path

file = Path(__file__).resolve()
package_root_directory = file.parents[1]
# print('__file__={0:<35} | __name__={1:<25} | __package__={2:<25}'.format(__file__,__name__,str(__package__)))

from wasmParser import parser

# Module-level RNG (unseeded by default — same behaviour as before)
_rng = np.random.default_rng()

def set_seed(seed):
    """Seed both numpy and stdlib random for reproducible runs.
    Only called when the user passes --seed on the CLI."""
    global _rng
    _rng = np.random.default_rng(seed)
    _stdlib_random.seed(seed)

# [-] (i)store(8-32), (i,f)load(_s/u)(8-32), (i,f)trunc(_i/f)(32/64)(_s/u), (i64)extend_i32(_s/u), (f32)convert_i(32/64)(_s/u), f64.promote_f32, (i/f)reinterpret_(i/f)(32/64)s
num_operand = {"add": 2, "sub":2, "mul": 2, "and": 2, "or": 2, "xor": 2, "shl": 2, "shr_s": 2, "shr_u": 2, "rotl": 2, "rotr": 2, \
       "lt": 2, "lt_s": 2, "lt_u": 2, "gt": 2, "gt_s": 2, "gt_u": 2, "le": 2, "le_s": 2, "le_u": 2, "ge": 2, "ge_s": 2, "ge_u": 2, \
               "ne": 2, "eqz": 1, "eq": 2, "neg": 1, \
                   "sqrt": 1, "min": 2, "max": 2, "copysign": 2, "abs": 1, "ceil": 1, "floor": 1, "nearest": 1
}
type_operand = {"add": ['i32', 'i64', 'f32', 'f64'], "sub": ['i32', 'i64', 'f32', 'f64'], "mul": ['i32', 'i64', 'f32', 'f64'], "and": ['i32', 'i64'], "or": ['i32', 'i64'], "xor": ['i32', 'i64'], "shl": ['i32', 'i64'], "shr_s": ['i32', 'i64'], "shr_u": ['i32', 'i64'], "rotl": ['i32', 'i64'], "rotr": ['i32', 'i64'], \
       "lt": ['f32', 'f64'], "lt_s": ['i32', 'i64'], "lt_u": ['i32', 'i64'], "gt": ['f32', 'f64'], "gt_s": ['i32', 'i64'], "gt_u": ['i32', 'i64'], "le": ['f32', 'f64'], "le_s": ['i32', 'i64'], "le_u": ['i32', 'i64'], "ge": ['f32', 'f64'], "ge_s": ['i32', 'i64'], "ge_u": ['i32', 'i64'], \
               "ne": ['i32', 'i64', 'f32', 'f64'], "eqz": ['i32', 'i64'], "eq": ['i32', 'i64', 'f32', 'f64'], "neg": ['f32', 'f64'], \
                   "sqrt": ['f32', 'f64'], "min": ['f32', 'f64'], "max": ['f32', 'f64'], "copysign": ['f32', 'f64'], "abs": ['f32', 'f64'], "ceil": ['f32', 'f64'], "floor": ['f32', 'f64'], "nearest": ['f32', 'f64']
}


#[-]div_s/u - i32/64
#[-]shr_s/u - i32/64
#[-]clz/ctz - i32/64
#[-] min, max, ceil, floors, trunc, nearest, sqrt
stack_opcodes = {"add": [2, ["i32", "i64", "f32", "f64"]], "sub": [2, ["i32", "i64", "f32", "f64"]], "mul": [2, ["i32", "i64", "f32", "f64"]], "div": [2, ["f32", "f64"]], \
    "and": [2, ["i32", "i64"]], "or": [2, ["i32", "i64"]], "xor": [2, ["i32", "i64"]], "shl": [2, ["i32", "i64"]], "shr_s": [2, ["i32", "i64"]], "shr_u": [2, ["i32", "i64"]], "rotl": [2, ["i32", "i64"]], "rotr": [2, ["i32", "i64"]], \
       "lt": [2, ["f32", "f64"]], "lt_s": [2, "i32", "i64"], "lt_u": [2, "i32", "i64"], "gt": [2, ["f32", "f64"]], "gt_s": [2, "i32", "i64"], "gt_u": [2, "i32", "i64"], \
           "le": [2, ["f32", "f64"]], "le_s": [2, "i32", "i64"], "le_u": [2, "i32", "i64"], "ge": [2, ["f32", "f64"]], "ge_s": [2, "i32", "i64"], "ge_u": [2, "i32", "i64"], \
               "ne": [2, ["i32", "i64", "f32", "f64"]], "eqz": [1, ["i32", "i64"]], "eq": [2, ["i32", "i64", "f32", "f64"]], "neg": [1, ["f32", "f64"]]
}

non_stack_opcodes = ["unreachable", "nop", "block", "loop", "if", "else", "end", "br", "return", "call"]
stack_effect = {"br_if":-1, "br_table":-1, "call_indirect":-1, "drop":-1, "set":-1, "eq":-1, "ne":-1, \
                "lt_s":-1, "lt_u":-1, "gt_s":-1, "gt_u":-1, "le_s":-1, "le_u":-1, "ge_s":-1, "ge_u":-1, \
                "select":-2, "store":-2, "store8":-2, "store16":-2, \
                    "load":0, "load8":0, "load16":0, "load8_s":0, "load8_u":0, "load16_s":0, "load16_u":0, "load32_s":0, "load32_u":0, "grow":0, \
                        "eqz":0, 
                        "get":1, "size":1, "const":1}

#[-] if, loop
crypto_opcodes = {"shr_u": [2, ["i32", "i64"]], "shr_s": [2, ["i32", "i64"]], "shl": [2, ["i32", "i64"]],  "xor": [2, ["i32", "i64"]],
}

non_crypto_opcodes = {"add": [2, ["i32", "i64", "f32", "f64"]], "sub": [2, ["i32", "i64", "f32", "f64"]], "mul": [2, ["i32", "i64", "f32", "f64"]], "div": [2, ["f32", "f64"]], \
    "and": [2, ["i32", "i64"]], "or": [2, ["i32", "i64"]], \
       "lt": [2, ["f32", "f64"]], "lt_s": [2, "i32", "i64"], "lt_u": [2, "i32", "i64"], "gt": [2, ["f32", "f64"]], "gt_s": [2, "i32", "i64"], "gt_u": [2, "i32", "i64"], \
           "le": [2, ["f32", "f64"]], "le_s": [2, "i32", "i64"], "le_u": [2, "i32", "i64"], "ge": [2, ["f32", "f64"]], "ge_s": [2, "i32", "i64"], "ge_u": [2, "i32", "i64"], \
               "ne": [2, ["i32", "i64", "f32", "f64"]], "eqz": [1, ["i32", "i64"]], "eq": [1, ["i32", "i64", "f32", "f64"]], "neg": [1, ["f32", "f64"]]
}


### v2
target_opcodes = ["add", "sub", "mul", "div", "and", "or", "xor", "shl", "shr_s", "shr_u", "rotl", "rotr"]
# target_opcodes = ["add", "sub", "mul", "div", "and", "or", "xor", "shl", "shr_s", "shr_u", "rotl", "rotr", \
#                   "lt", "lt_s", "lt_u", "gt", "gt_s", "gt_u", "le", "le_s", "le_u", "ge", "ge_s", "ge_u", \
#                       "ne", "eqz", "eq", "neg"]





def getOpcodes(flag):
    if flag == 0:
        return crypto_opcodes
    elif flag == 1:
        return stack_opcodes
    elif flag == 2:
        return non_crypto_opcodes

#######Global
# DUMMY_GLOBAL_ADDED = False
LAST_GLOBAL_ID = 9999

DUMMY_GLOBALS = dict()
EXTRA_GLOBALS = {"i32":list(), "i64":list(), "f32":list(), "f64":list()}

ELEM_PARAMS = dict()

EXCLUDED = {
    # control flow
    "block","loop","if","else","end",
    "br","br_if","br_table","return",
    "call","call_indirect","drop","select",
    # memory-write
    *[f"{t}.store{sz}" for t in ("i32","i64","f32","f64")
      for sz in ("","8","8_s","8_u","16","16_s","16_u","32","32_s","32_u","32","32_s","32_u")],
    "memory.grow",
}

CANONICAL_ARITY = {
    # loads
    'f32.load':   1,
    'f64.load':   1,
    'i32.load':   1,
    'i64.load':   1,

    # integer binary ops
    'i32.add':    2,
    'i32.and':    2,
    'i32.div_s':  2,  
    'i32.mul':    2,
    'i32.or':     2,
    'i32.rem_s':  2,  
    'i32.rotl':   2,
    'i32.rotr':   2,
    'i32.shl':    2,
    'i32.shr_s':  2, 
    'i32.sub':    2,
    'i32.xor':    2,

    'i64.add':    2,
    'i64.and':    2,
    'i64.div_s':  2,
    'i64.mul':    2,
    'i64.or':     2,
    'i64.rem_s':  2,
    'i64.rotl':   2,
    'i64.rotr':   2,
    'i64.shl':    2,
    'i64.shr_s':  2,
    'i64.sub':    2,
    'i64.xor':    2,

    # float binary ops
    'f32.add':    2,
    'f32.and':    2,
    'f32.div_s':  2,
    'f32.mul':    2,
    'f32.or':     2,
    'f32.rem_s':  2,
    'f32.rotl':   2,
    'f32.rotr':   2,
    'f32.shl':    2,
    'f32.shr_s':  2,
    'f32.sub':    2,
    'f32.xor':    2,

    'f64.add':    2,
    'f64.and':    2,
    'f64.div_s':  2,
    'f64.mul':    2,
    'f64.or':     2,
    'f64.rem_s':  2,
    'f64.rotl':   2,
    'f64.rotr':   2,
    'f64.shl':    2,
    'f64.sub':    2,
    'f64.xor':    2,

    # comparisons
    'i32.eq':    2,
    'i32.ge_s':  2,
    'i32.gt_s':  2,
    'i32.le_s':  2,
    'i32.lt_s':  2,
    'i32.ne':    2,
    'i64.eq':    2,
    'i64.ge_s':  2,
    'i64.gt_s':  2,
    'i64.le_s':  2,
    'i64.lt_s':  2,
    'i64.ne':    2,
    'f32.eq':    2,
    'f32.ge_s':  2,
    'f32.gt_s':  2,
    'f32.le_s':  2,
    'f32.lt_s':  2,
    'f32.ne':    2,
    'f64.eq':    2,
    'f64.ge_s':  2,
    'f64.gt_s':  2,
    'f64.le_s':  2,
    'f64.lt_s':  2,
    'f64.ne':    2,

    # integer unary
    'i32.clz':   1,
    'i32.ctz':   1,
    'i32.eqz':   1,
    'i32.popcnt':1,
    'i64.clz':   1,
    'i64.ctz':   1,
    'i64.eqz':   1,
    'i64.popcnt':1,

    # locals/globals
    'global.get':0,
    'local.get': 0,
    'local.tee': 1,
}

# 연산별 operand 개수
OP_ARITY = {
    # memory
    'load':      1,  # 주소
    # integer/float binary
    'add':       2,
    'sub':       2,
    'mul':       2,
    'div_s':     2,
    'rem_s':     2,
    'and':       2,
    'or':        2,
    'xor':       2,
    'shl':       2,
    # 'shr_s':     2,
    'rotl':      2,
    # 'rotr':      2,
    # comparisons
    'eq':        2,
    'ne':        2,
    'lt_s':      2,
    'gt_s':      2,
    'le_s':      2,
    'ge_s':      2,
    # unary
    'clz':       1,
    # 'ctz':       1,
    'popcnt':    1,
    'eqz':       1,
    # locals/globals
    'get':       0,  # local.get / global.get
    # 'tee':       1,  # local.tee
}

# 스택에서 소비하는 피연산자 수
OP_ARITY_MEMORY = {
    'load':        0,   
    'load8_s':     0,   
    'load8_u':     0,   
    'load16_s':    0,   
    'load16_u':    0,  
    'load32_s':    0,   
    'load32_u':    0,   
    'size':        0,   
    'get':         0,   
    'tee':         0,   
}
OP_TYPE_MEMORY = {
    'load':        ['i32', 'i64', 'f32', 'f64'],    
    'load8_s':     ['i32', 'i64'],
    'load8_u':     ['i32', 'i64'],
    'load16_s':    ['i32', 'i64'],
    'load16_u':    ['i32', 'i64'],
    'load32_s':    ['i64'],
    'load32_u':    ['i64'],
    'size':        ['memory'],          
    'get':         ['local', 'global'],          
    'tee':         ['local']
}  

OP_ARITY_NUMERIC = {
    'add':   2,
    'sub':   2,
    'mul':   2,
    'div':   2,    
    'div_s': 2,    
    'div_u': 2,    
    'rem_s': 2,    
    'rem_u': 2,    
}
OP_TYPE_NUMERIC= {
    'add':   ['i32', 'i64', 'f32', 'f64'],
    'sub':   ['i32', 'i64', 'f32', 'f64'],
    'mul':   ['i32', 'i64', 'f32', 'f64'],
    'div':   ['f32', 'f64'],     
    'div_s': ['i32', 'i64'],     
    'div_u': ['i32', 'i64'],     
    'rem_s': ['i32', 'i64'],     
    'rem_u': ['i32', 'i64'],    
}



OP_ARITY_BIT = {
    'shl':     2,
    'shr_s':   2,
    'shr_u':   2,
    'rotl':    2,
    'rotr':    2,
    'and':     2,
    'or':      2,
    'xor':     2,
    'clz':     1,
    'ctz':     1,
    'popcnt':  1,
}
OP_TYPE_BIT = {
    'shl':     ['i32', 'i64'],
    'shr_s':   ['i32', 'i64'],
    'shr_u':   ['i32', 'i64'],
    'rotl':    ['i32', 'i64'],
    'rotr':    ['i32', 'i64'],
    'and':     ['i32', 'i64'],
    'or':      ['i32', 'i64'],
    'xor':     ['i32', 'i64'],
    'clz':     ['i32', 'i64'],
    'ctz':     ['i32', 'i64'],
    'popcnt':  ['i32', 'i64'],
}

OP_ARITY_CONVERSION1 = {
    'i32.wrap_i64':        1,  
    'i64.extend_i32_s':    1,  
    'i64.extend_i32_u':    1,  
    'f32.trunc':          1,
    'f64.trunc':          1,
    'i32.trunc_f32_s':     1,  
    'i64.trunc_f32_s':     1,  
    'i32.trunc_f32_u':     1,  
    'i64.trunc_f32_u':     1,  
    'i32.trunc_f64_s':     1,  
    'i64.trunc_f64_s':     1,  
    'i32.trunc_f64_u':     1,  
    'i64.trunc_f64_u':     1,
    'f32.convert_i32_s':    1,
    'f32.convert_i32_u':    1,
    'f32.convert_i64_s':    1,
    'f32.convert_i64_u':    1,
    'f64.convert_i32_s':    1,
    'f64.convert_i32_u':    1,
    'f64.convert_i64_s':    1,
    'f64.convert_i64_u':    1
}
OP_TYPE_CONVERSION1 = {
    'i32.wrap_i64':        ['i64'],
    'i64.extend_i32_s':    ['i32'],
    'i64.extend_i32_u':    ['i32'],
    'f32.trunc':          ['f32'],
    'f64.trunc':          ['f64'],
    'i32.trunc_f32_s':     ['f32'],
    'i64.trunc_f32_s':     ['f32'],
    'i32.trunc_f32_u':     ['f32'],
    'i64.trunc_f32_u':     ['f32'],
    'i32.trunc_f64_s':     ['f64'],
    'i64.trunc_f64_s':     ['f64'],
    'i32.trunc_f64_u':     ['f64'],
    'i64.trunc_f64_u':     ['f64'],
    'f32.convert_i32_s':    ['i32'],
    'f32.convert_i32_u':    ['i32'],
    'f32.convert_i64_s':    ['i64'],
    'f32.convert_i64_u':    ['i64'],
    'f64.convert_i32_s':    ['i32'],
    'f64.convert_i32_u':    ['i32'],
    'f64.convert_i64_s':    ['i64'],
    'f64.convert_i64_u':    ['i64']
}

OP_ARITY_CONVERSION2 = {
    'f64.promote_f32':      1,
    'f32.demote_f64':       1,
    'i32.reinterpret_f32':  1,
    'i64.reinterpret_f64':  1,
    'f32.reinterpret_i32':  1,
    'f64.reinterpret_i64':  1
}
OP_TYPE_CONVERSION2 = {
    'f64.promote_f32':      ['f32'],
    'f32.demote_f64':       ['f64'],
    'i32.reinterpret_f32':  ['f32'],
    'i64.reinterpret_f64':  ['f64'],
    'f32.reinterpret_i32':  ['i32'],
    'f64.reinterpret_i64':  ['i64']
}


OP_ARITY_FLOATING = {
    'abs':       1,
    'neg':       1,
    'ceil':      1,
    'floor':     1,
    'nearest':   1,
    'sqrt':      1,
    'min':       2,
    'max':       2,
    'copysign':  2,
}
OP_TYPE_FLOATING = {
    'abs':       ['f32', 'f64'],
    'neg':       ['f32', 'f64'],
    'ceil':      ['f32', 'f64'],
    'floor':     ['f32', 'f64'],
    'nearest':   ['f32', 'f64'],
    'sqrt':      ['f32', 'f64'],
    'min':       ['f32', 'f64'],
    'max':       ['f32', 'f64'],
    'copysign':  ['f32', 'f64'],
}


OP_ARITY = {
    'add':   ['i32','i64','f32','f64'],
    'and':   ['i32','i64','f32','f64'],
    'clz':   ['i32','i64'],
    'ctz':   ['i32','i64'],
    'eqz':   ['i32','i64'],
    'popcnt':['i32','i64'],

    'div_s': ['i32','i64','f32','f64'],
    'rem_s': ['i32','i64','f32','f64'],

    'mul':   ['i32','i64','f32','f64'],
    'or':    ['i32','i64','f32','f64'],
    'sub':   ['i32','i64','f32','f64'],
    'xor':   ['i32','i64','f32','f64'],

    'rotl':  ['i32','i64','f32','f64'],
    'rotr':  ['i32','i64','f32','f64'],
    'shl':   ['i32','i64','f32','f64'],
    'shr_s': ['i32','i64','f32','f64'],

    'eq':    ['i32','i64','f32','f64'],
    'ne':    ['i32','i64','f32','f64'],
    'lt_s':  ['i32','i64','f32','f64'],
    'gt_s':  ['i32','i64','f32','f64'],
    'le_s':  ['i32','i64','f32','f64'],
    'ge_s':  ['i32','i64','f32','f64'],

    'load':  ['i32'],

    # locals/globals
    'get':   ['local','global'],
    'tee':   ['local'],
}



#############################

def get_dist(_alpha, _beta):

    # np.random.seed(int(time.time()))

    return _rng.beta(_alpha, _beta)
    # return beta.rvs(float(_alpha), float(_beta))

def getDist(_alpha, _beta, _length):

    # [TY] -1?
    return int(_rng.beta(1, 1)*_length)
    
def add_global(parsedSection, pt_type):
    
    global LAST_GLOBAL_ID
    
    if LAST_GLOBAL_ID == 9999:
        globalIDs = list(parsedSection["Global"].keys())
        LAST_GLOBAL_ID= int(globalIDs[-1])
    
    # print(parsedSection['Global'][str(LAST_GLOBAL_ID)])
    this_indent = parser.retIndent(parsedSection['Global'][str(LAST_GLOBAL_ID)].line[0])
    
    EXTRA_GLOBALS[pt_type].append(LAST_GLOBAL_ID+1)
    # print(LAST_GLOBAL_ID)
    LAST_GLOBAL_ID += 1
    # print(LAST_GLOBAL_ID)
    
    new_global = f"{this_indent}(global (;{LAST_GLOBAL_ID};) (mut {pt_type}) ({pt_type}.const 0))\n"
    # print(new_global)
    parsedSection['Global'][str(LAST_GLOBAL_ID)] = ss.GLOBAL(line=[new_global,'+'])