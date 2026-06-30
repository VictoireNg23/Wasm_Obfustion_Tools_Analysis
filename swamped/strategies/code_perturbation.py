from strategies import state
import random
import math
import pickle as pkl
import re
import os

# import wasmParser.parser
# from importlib import reload
# reload(state)
# reload(wasmParser.parser)

from wasmParser.parser import retIndent
from wasmParser.parser import retType
from wasmParser import sectionStructure as ss

##########test
import numpy as np
import matplotlib.pyplot as plt

from strategies.state import getDist
import strategies.state
from wasmParser.parser import insert_after_key


def nop_insertion(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        nop_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                nop_offset_list.append(offset)

        if len(nop_offset_list) == 0:
            continue
            
        iter = round(len(nop_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha, beta, len(nop_offset_list))
                beta_idx = max(0, min(beta_idx, len(nop_offset_list) - 1))
                selected_offset = nop_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):
            if offset in target_offset_list:
                indent = retIndent(body[offset][0])
                new_body.append([body[offset][0] + f'{indent}nop\n','NopInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body




def stackOP_insertion_memory(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    # print(ops)

    for f in functions:
        ops = list(state.OP_ARITY_MEMORY)
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        local_ids = re.findall(r'\(local\s+(\$\w+)', parsedSection['Function'][f].header[-1][0])
        global_ids = list(parsedSection['Global'].keys())

        # print(ops)
        if len(local_ids) == 0:
            ops.remove('tee')
            if len(global_ids) == 0:
                ops.remove('get')
        
        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])


            if offset in target_offset_list:
                beta = getDist(alpha,beta,len(ops))
                beta = max(0, min(beta, len(ops) - 1))
                op = ops[beta]
                base_type = state.OP_TYPE_MEMORY[op]

                beta = getDist(alpha,beta,len(base_type))
                beta = max(0, min(beta, len(base_type) - 1))
                new_type = base_type[beta]
                if new_type == 'local' and len(local_ids)==0:
                    new_type = 'global'
                elif new_type == 'global' and len(global_ids)==0:
                    new_type = 'local'
                
                if new_type == 'local':
                    beta_ret = getDist(alpha,beta,len(local_ids))
                    beta_ret = max(0, min(beta_ret, len(local_ids) - 1))
                    # print(beta_ret, len(local_ids))
                    new_idx = local_ids[beta_ret] 
                    new_code =  f"{indent}local.get {new_idx}\n{indent}drop\n"
                elif new_type == 'global':
                    beta = getDist(alpha,beta,len(global_ids))
                    beta = max(0, min(beta, len(global_ids) - 1))
                    new_idx = global_ids[beta] 
                    new_code = f"{indent}global.get {new_idx}\n{indent}drop\n"
                elif new_type == 'memory':
                    new_code = f'{indent}{new_type}.{op}\n{indent}drop\n'
                else:
                    new_operand = f"{indent}i32.const 0\n"
                    new_code = new_operand+f'{indent}{new_type}.{op}\n{indent}drop\n'

                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body


def stackOP_insertion_numeric(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    ops = list(state.OP_ARITY_NUMERIC)

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])

            beta = getDist(alpha,beta,len(ops))
            beta = max(0, min(beta, len(ops) - 1))
            op = ops[beta]
            base_type = state.OP_TYPE_NUMERIC[op]

            if offset in target_offset_list:
                beta = getDist(alpha,beta,len(base_type))
                beta = max(0, min(beta, len(base_type) - 1))
                new_type = base_type[beta]

                new_operand = str()
                val = random.randint(-10, 10)
                for _ in range(2):
                    val = random.randint(-10, 10)
                    new_operand +=  f"{indent}{new_type}.const {val}\n"
                new_code = new_operand+f'{indent}{new_type}.{op}\n{indent}drop\n'
                
                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body


def stackOP_insertion_bit(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    ops = list(state.OP_ARITY_BIT)

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])

            beta = getDist(alpha,beta,len(ops))
            beta = max(0, min(beta, len(ops) - 1))
            op = ops[beta]
            base_type = state.OP_TYPE_BIT[op]

            if offset in target_offset_list:
                beta = getDist(alpha,beta,len(base_type))
                beta = max(0, min(beta, len(base_type) - 1))
                new_type = base_type[beta]


                new_operand = str()
                for _ in range(state.OP_ARITY_BIT[op]):
                    val = random.randint(-10, 10)
                    new_operand +=  f"{indent}{new_type}.const {val}\n"
                new_code = new_operand+f'{indent}{new_type}.{op}\n{indent}drop\n'
                
                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body


def stackOP_insertion_conversion1(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    ops = list(state.OP_ARITY_CONVERSION1)

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])

            beta_idx = getDist(alpha,beta,len(ops))
            beta_idx = max(0, min(beta_idx, len(ops) - 1))
            op = ops[beta_idx]
            base_type = state.OP_TYPE_CONVERSION1[op]

            if offset in target_offset_list:
                beta_idx = getDist(alpha,beta,len(base_type))
                beta_idx = max(0, min(beta_idx, len(base_type) - 1))
                new_type = base_type[beta_idx]

                val = random.randint(-10, 10)
                new_operand =  f"{indent}{new_type}.const {val}\n"
                new_code = new_operand+f'{indent}{op}\n{indent}drop\n'
                
                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body

def stackOP_insertion_conversion2(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    ops = list(state.OP_ARITY_CONVERSION2)

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])

            beta_idx = getDist(alpha,beta,len(ops))
            beta_idx = max(0, min(beta_idx, len(ops) - 1))
            op = ops[beta_idx]
            base_type = state.OP_TYPE_CONVERSION2[op]

            if offset in target_offset_list:
                beta_idx = getDist(alpha,beta,len(base_type))
                beta_idx = max(0, min(beta_idx, len(base_type) - 1))
                new_type = base_type[beta_idx]

                val = random.randint(-10, 10)
                new_operand =  f"{indent}{new_type}.const {val}\n"
                new_code = new_operand+f'{indent}{op}\n{indent}drop\n'
                
                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body

def stackOP_insertion_floating(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']
    ops = list(state.OP_ARITY_FLOATING)

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        OP_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
                OP_offset_list.append(offset)

        if len(OP_offset_list) == 0:
            continue
            
        iter = round(len(OP_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(OP_offset_list))
                beta_idx = max(0, min(beta_idx, len(OP_offset_list) - 1))
                selected_offset = OP_offset_list[beta_idx]

                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):

            indent = retIndent(body[offset][0])

            beta_idx = getDist(alpha,beta,len(ops))
            beta_idx = max(0, min(beta_idx, len(ops) - 1))
            op = ops[beta_idx]
            base_type = state.OP_TYPE_FLOATING[op]

            if offset in target_offset_list:
                beta_idx = getDist(alpha,beta,len(base_type))
                beta_idx = max(0, min(beta_idx, len(base_type) - 1))
                new_type = base_type[beta_idx]

                new_operand = str()
                val = random.randint(-10, 10)
                for _ in range(state.OP_ARITY_FLOATING[op]):
                    val = random.randint(-10, 10)
                    new_operand +=  f"{indent}{new_type}.const {val}\n"
                new_code = new_operand+f'{indent}{new_type}.{op}\n{indent}drop\n'
                
                new_body.append(body[offset])
                new_body.append([new_code,'StackOPInsertion'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body


def add_sub_transformation(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        add_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if (offset>0) and ('add' in code[0]) and ('.const' in body[offset-1][0]):
                add_offset_list.append(offset)

        if len(add_offset_list) == 0:
            continue
            
        iter = round(len(add_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(add_offset_list))
                beta_idx = max(0, min(beta_idx, len(add_offset_list) - 1))
                # if beta_idx == len(add_offset_list):
                #     beta_idx -= 1
                # print(len(add_offset_list), beta_idx)
                selected_offset = add_offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        
        new_body = list()
        for offset in range(len(body)):
            if (offset+1) in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.const\s+(?P<value>-?\d+)',
                    lambda m: f"{m.group('indent')}{m.group('type')}.const {-int(m.group('value'))}",
                    code
                )
                new_body.append([new_code,'AddSubTransformation'])
            elif offset in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.add\b',
                    lambda m: f"{m.group('indent')}{m.group('type')}.sub",
                    code
                )
                new_body.append([new_code,'AddSubTransformation'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body

def sub_add_transformation(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        sub_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if (offset>0) and ('sub' in code[0]) and ('.const' in body[offset-1][0]):
                sub_offset_list.append(offset)

        if len(sub_offset_list) == 0:
            continue
            
        iter = round(len(sub_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(sub_offset_list))
                beta_idx = max(0, min(beta_idx, len(sub_offset_list) - 1))
                # if beta_idx == len(sub_offset_list):
                #     beta_idx -= 1
                # print(len(sub_offset_list), beta_idx)
                selected_offset = sub_offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        # print(target_offset_list)
        new_body = list()
        for offset in range(len(body)):
            if (offset+1) in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.const\s+(?P<value>-?\d+)',
                    lambda m: f"{m.group('indent')}{m.group('type')}.const {abs(int(m.group('value')))}",
                    code
                )
                new_body.append([new_code,'SubAddTransformation'])
            elif offset in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.sub\b',
                    lambda m: f"{m.group('indent')}{m.group('type')}.add",
                    code
                )
                new_body.append([new_code,'SubAddTransformation'])
            else:
                new_body.append(body[offset])

        parsedSection['Function'][f].body = new_body


def shift_transformation(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        shift_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if offset > 0 \
                and any(op in code[0] for op in ('.shl', '.shr_u')) \
                and '.const' in body[offset-1][0]:
                    shift_offset_list.append(offset)

        if len(shift_offset_list) == 0:
            continue
            
        iter = round(len(shift_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(shift_offset_list))
                beta_idx = max(0, min(beta_idx, len(shift_offset_list) - 1))
                selected_offset = shift_offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        # print(f, target_offset_list)
        # if f=='$f23':
        #     print(body[3][0])
        new_body = list()
        for offset in range(len(body)):
            if (offset+1) in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.const\s+(?P<value>-?\d+)',
                    lambda m: f"{m.group('indent')}{m.group('type')}.const {1 << abs(int(m.group('value')))}",
                    code
                )
                # if f=='$f23':
                    # print(code,new_code)
                new_body.append([new_code, 'ShiftTransformation'])
            elif offset in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.(?P<op>shl|shr_u)\b',
                    lambda m: f"{m.group('indent')}{m.group('type')}.{'mul' if m.group('op')=='shl' else 'div_u'}",
                    code
                )
                # if f=='$f23':
                    # print(code,new_code)
                new_body.append([new_code, 'ShiftTransformation'])
            else:
                new_body.append(body[offset])
            

        parsedSection['Function'][f].body = new_body


def eqz_transformation(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        eqz_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if offset > 0 and ('eqz') in code[0]:
                    eqz_offset_list.append(offset)

        if len(eqz_offset_list) == 0:
            continue
            
        iter = round(len(eqz_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(eqz_offset_list))
                beta_idx = max(0, min(beta_idx, len(eqz_offset_list) - 1))
                selected_offset = eqz_offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        # print(f, target_offset_list)

        new_body = list()
        for offset in range(len(body)):
            if offset in target_offset_list:
                code = body[offset][0]
                new_code = re.sub(
                    r'(?P<indent>\s*)(?P<type>\w+)\.eqz\b',
                    lambda m: (
                        f"{m.group('indent')}{m.group('type')}.const 0\n"
                        f"{m.group('indent')}{m.group('type')}.eq"
                    ),
                    code
                )
                new_body.append([new_code, 'EqzTransformation'])
            else:
                new_body.append(body[offset])
            

        parsedSection['Function'][f].body = new_body

def load_store_transformation(parsedSection, alpha, beta, ratio):
    functions = parsedSection['Function']

    RE_MEM_OFFSET = re.compile(
        r'(?P<indent>\s*)'             
        r'(?P<type>\w+)\.'              
        r'(?P<op>load(?:|8_[su]|16_[su]|32_[su])|store(?:8|16|32)?)\b'       
        r'(?P<after>[^;]*)'            
        r'\boffset=(?P<offset>\d+)\b'     
    )

    def repl(m):
        indent = m.group('indent')
        type = m.group('type')
        op = m.group('op')
        offset = m.group('offset')
        after = m.group('after')
        
        if op == 'load':
            return (
                f"{indent}i32.const {offset}\n"
                f"{indent}i32.add\n"
                f"{indent}{type}.{op}{after}"
            )

        if type == 'store':
            return (
                f"{indent}i64.const {offset}\n"
                f"{indent}i64.add\n"
                f"{indent}i32.wrap_i64\n"
                f"{indent}{type}.{op}{after}"
            )
        else:
            return (
                f"{indent}i32.const {offset}\n"
                f"{indent}i32.add\n"
                f"{indent}{type}.{op}{after}"
            )

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        else:
            body = function.body

        memory_offset_list = list()

        for offset, code in enumerate(body):
            # print(code)
            if offset > 0 and re.match(RE_MEM_OFFSET,code[0]):
                    memory_offset_list.append(offset)

        if len(memory_offset_list) == 0:
            continue
            
        iter = round(len(memory_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        target_offset_list = list()
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(memory_offset_list))
                beta_idx = max(0, min(beta_idx, len(memory_offset_list) - 1))
                selected_offset = memory_offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break
        # print(f, target_offset_list)

        new_body = list()
        new_locals = {'i32':0, 'i64':0, 'f32':0, 'f64':0}

        for offset in range(len(body)):
            if offset in target_offset_list:
                code = body[offset][0]
                MEM_MATCH = re.match(RE_MEM_OFFSET, code)
                
                indent = MEM_MATCH.group('indent')
                type = MEM_MATCH.group('type')
                op = MEM_MATCH.group('op')
                offset = MEM_MATCH.group('offset')
                after = MEM_MATCH.group('after')

                if 'load' in op:
                    new_code = (
                        f"{indent}i32.const {offset}\n"
                        f"{indent}i32.add\n"
                        f"{indent}{type}.{op}{after}\n"
                    )
                elif 'store' in op:
                    new_code = (
                        f"{indent}local.set $wade{type}\n"
                        f"{indent}i32.const {offset}\n"
                        f"{indent}i32.add\n"
                        f"{indent}local.get $wade{type}\n"
                        f"{indent}{type}.{op}{after}\n"
                    )
                    new_locals[type] = 1

                new_body.append([new_code, 'LoadStoreTransformation'])

            else:
                new_body.append(body[offset])

        new_local_str = str() 
        for type in new_locals:
            if new_locals[type] == 1:
                new_local_str += f' (local $wade{type} {type})'

        function_header = parsedSection['Function'][f].header
        last_header_line = function_header[-1][0]
        function_header[-1] = [last_header_line.replace('\n',new_local_str+'\n'),'LoadStoreTransformation']
        parsedSection['Function'][f].header = function_header

        parsedSection['Function'][f].body = new_body


def direct_to_indirect(parsedSection, alpha, beta, ratio):

    RE_FUNC_TYPE = re.compile(
        r'\(func\s+'                    
        r'(?P<funcID>\$[^\s()]+)\s*'     
        r'\(\s*type\s+'                     
        r'(?P<type>\$[^\s()]+)\s*'         
        r'\)\s*\)'                       
    )
    
    functions = parsedSection['Function']
    func_keys = list(functions.keys())

    funcID_type = dict()
    for i in parsedSection['Import']:
        import_entry = parsedSection['Import'][i]
        if import_entry.type == 'func':
            MATCH_FUNC = RE_FUNC_TYPE.search(import_entry.line[0])
            if MATCH_FUNC:
                funcID_type[MATCH_FUNC.group('funcID')] = MATCH_FUNC.group('type')
    for f in parsedSection['Function']:
        funcID_type[f] = parsedSection['Function'][f].type

    funcID_to_index = dict()

    for f in functions:
        # if f != '$f23':
        #     continue

        function = parsedSection['Function'][f]

        if function.body == None:
            continue
        
        body = function.body

        offset_list = list()
        # offset_funcID = dict()
        for offset, code in enumerate(body):
            code_line = code[0].strip()
            if code_line.startswith('call '):
                offset_list.append(offset)

        if len(offset_list) == 0:
            continue

        iter = round(len(offset_list)*ratio)
        if iter == 0:
            iter = 1

        target_offset_list = list()
        
        for _ in range(iter):
            while True:
                
                beta_idx = getDist(alpha,beta,len(offset_list))
                beta_idx = max(0, min(beta_idx, len(offset_list) - 1))
                selected_offset = offset_list[beta_idx]
                if selected_offset not in target_offset_list:
                    target_offset_list.append(selected_offset)
                    break

        new_body = list()
        for offset in range(len(body)):
            code = body[offset][0]
            if offset in target_offset_list:
                indent = retIndent(code)

                funcID = code.split('call ')[1].strip()
                if funcID in funcID_to_index:
                    func_index = funcID_to_index[funcID]
                else:
                    func_index = len(funcID_to_index)
                    funcID_to_index[funcID] = func_index
                
                func_type = funcID_type[funcID]
                new_body_code = f'{indent}i32.const {func_index}\n{indent}call_indirect $wadetable (type {func_type})\n'
                new_body.append([new_body_code, 'DirectToIndirect'])
                # print(new_body_code)
            else:
                # print(code)
                new_body.append([code, ''])
        functions[f].body = new_body
        # print(functions[f].body)


    table_keys = parsedSection['Table'].keys()
    if len(table_keys) != 0:
        last_table = list(table_keys)[-1]
        new_table_code = [f'  (table $wadetable {len(funcID_to_index)} funcref)\n','DirectToIndirect']
        new_table = ss.TABLE(line=new_table_code)
        insert_after_key(parsedSection['Table'], last_table, '$wadetable', new_table)
    else:
        new_table_code = [f'  (table $wadetable {len(funcID_to_index)} funcref)\n','DirectToIndirect']
        parsedSection['Table'] = {"$wadetable": ss.TABLE(line=new_table_code)}

    element_keys = parsedSection['Element'].keys()
    func_list = ' '.join(str(k) for k in funcID_to_index.keys())
    if len(element_keys) != 0:
        last_element = list(element_keys)[-1]
        new_element_code = [f'  (elem $wadeelem (table $wadetable) {func_list})\n','DirectToIndirect']
        new_element = ss.ELEMENT(line=new_element_code)
        insert_after_key(parsedSection['Element'], last_element, '$wadetable', new_element)
    else:
        new_element_code = [f'  (elem $wadeelem (table $wadetable) {func_list})\n','DirectToIndirect']
        parsedSection['Element'] = {"$wadeelem": ss.ELEMENT(line=new_element_code)}



def xor_MBA_transformation(parsedSection, alpha, beta, ratio=0):
    
    types = ['i32', 'i64', 'f32', 'f64']

    new_global_code = str()
    for t in types:
        new_global_code += f"  (global $wade{t}1 (mut {t}) ({t}.const 0))\n"
        new_global_code += f"  (global $wade{t}2 (mut {t}) ({t}.const 0))\n"
    
    global_keys = list(parsedSection['Global'].keys())
    new_global = ss.GLOBAL(line=[new_global_code, "MBATransformation+"])
    if len(global_keys) == 0:
        parsedSection['Global']['wadeglobal'] = new_global
    else:
        last_global = global_keys[-1]
        insert_after_key(parsedSection['Global'],last_global,'wadeglobal',new_global)
    
    current_dir = os.path.dirname(__file__)
    rule_path = os.path.join(current_dir, "data", "wasm_xor_rule.pkl")
    with open(rule_path, 'rb') as fr:
        xor_rules = pkl.load(fr)
    
    functions = parsedSection['Function']
    
    for f in functions:

        xor_offset_list = list()
        body = functions[f].body
        
        ## [error handler]
        if body == None:
            continue
        
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            if (".xor" in this_line):
                xor_offset_list.append(b_idx)
        if len(xor_offset_list) == 0:
            continue
        
        iter = round(len(xor_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        # print(xor_offset_list[0])
        # print('len:',len(xor_offset_list))
        
        target_lines = list()
        for _ in range(0,iter):
            while True:
                beta_idx = getDist(alpha,beta,len(xor_offset_list))
                beta_idx = max(0, min(beta_idx, len(xor_offset_list) - 1))
                # print(beta_idx)
                # print(xor_offset_list[beta_idx])
                selected_offset = xor_offset_list[beta_idx]

                if selected_offset not in target_lines:
                    target_lines.append(selected_offset)
                    break
        
        new_body = list()
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            
            if b_idx in target_lines:
                pt_type = retType(this_line)
                pt_indent = retIndent(this_line)
                
                xor_rule = random.choice(xor_rules)
                this_indent = retIndent(this_line)
                   
                new_body.append([f'{this_indent}global.set $wade{pt_type}2\n', 'MBATransformation'])
                new_body.append([f'{this_indent}global.set $wade{pt_type}1\n', 'MBATransformation'])
                
                for x in xor_rule:
                    new_body.append([pt_indent + x.replace('[type]',pt_type).replace('[x]',f'$wade{pt_type}1').replace('[y]',f'$wade{pt_type}2')+'\n', 'MBATransformation'])
            else:
                new_body.append([this_line, ''])
            
        parsedSection['Function'][f].body = new_body 

def or_MBA_transformation(parsedSection, alpha, beta, ratio=0):
    
    types = ['i32', 'i64', 'f32', 'f64']

    new_global_code = str()
    for t in types:
        new_global_code += f"  (global $wade{t}1 (mut {t}) ({t}.const 0))\n"
        new_global_code += f"  (global $wade{t}2 (mut {t}) ({t}.const 0))\n"
    
    global_keys = list(parsedSection['Global'].keys())
    new_global = ss.GLOBAL(line=[new_global_code, "MBATransformation+"])
    if len(global_keys) == 0:
        parsedSection['Global']['wadeglobal'] = new_global
    else:
        last_global = global_keys[-1]
        insert_after_key(parsedSection['Global'],last_global,'wadeglobal',new_global)
    
    current_dir = os.path.dirname(__file__)
    rule_path = os.path.join(current_dir, "data", "wasm_or_rule.pkl")
    with open(rule_path, 'rb') as fr:
        xor_rules = pkl.load(fr)
    
    functions = parsedSection['Function']
    
    for f in functions:

        xor_offset_list = list()
        body = functions[f].body
        
        ## [error handler]
        if body == None:
            continue
        
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            if (".or" in this_line):
                xor_offset_list.append(b_idx)
        if len(xor_offset_list) == 0:
            continue
        
        iter = round(len(xor_offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        # print(xor_offset_list[0])
        # print('len:',len(xor_offset_list))
        
        target_lines = list()
        for _ in range(0,iter):
            while True:
                beta_idx = getDist(alpha,beta,len(xor_offset_list))
                beta_idx = max(0, min(beta_idx, len(xor_offset_list) - 1))
                # print(beta_idx)
                # print(xor_offset_list[beta_idx])
                selected_offset = xor_offset_list[beta_idx]

                if selected_offset not in target_lines:
                    target_lines.append(selected_offset)
                    break
        
        new_body = list()
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            
            if b_idx in target_lines:
                pt_type = retType(this_line)
                pt_indent = retIndent(this_line)
                
                xor_rule = random.choice(xor_rules)
                this_indent = retIndent(this_line)
                   
                new_body.append([f'{this_indent}global.set $wade{pt_type}2\n', 'MBATransformation'])
                new_body.append([f'{this_indent}global.set $wade{pt_type}1\n', 'MBATransformation'])
                
                for x in xor_rule:
                    new_body.append([pt_indent + x.replace('[type]',pt_type).replace('[x]',f'$wade{pt_type}1').replace('[y]',f'$wade{pt_type}2')+'\n', 'MBATransformation'])
            else:
                new_body.append([this_line, ''])
            
        parsedSection['Function'][f].body = new_body     

def constant_global_variables(parsedSection, alpha, beta, ratio=0):
    
    types = ['i32', 'i64', 'f32', 'f64']

    new_global_code = str()
    for t in types:
        new_global_code += f"  (global $wade{t} (mut {t}) ({t}.const 0))\n"
        
    global_keys = list(parsedSection['Global'].keys())
    new_global = ss.GLOBAL(line=[new_global_code, ""])
    if len(global_keys) == 0:
        parsedSection['Global']['wadeglobal'] = new_global
    else:
        last_global = global_keys[-1]
        insert_after_key(parsedSection['Global'],last_global,'wadeglobal',new_global)
    
    
    functions = parsedSection['Function']
    
    for f in functions:

        offset_list = list()
        body = functions[f].body
        
        ## [error handler]
        if body == None:
            continue
        
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            if (".const " in this_line):
                offset_list.append(b_idx)
        if len(offset_list) == 0:
            continue
        
        iter = round(len(offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        # print(xor_offset_list[0])
        # print('len:',len(xor_offset_list))
        
        target_lines = list()
        for _ in range(0,iter):
            while True:
                beta_idx = getDist(alpha,beta,len(offset_list))
                beta_idx = max(0, min(beta_idx, len(offset_list) - 1))
                # print(beta_idx)
                # print(xor_offset_list[beta_idx])
                selected_offset = offset_list[beta_idx]

                if selected_offset not in target_lines:
                    target_lines.append(selected_offset)
                    break
        
        new_body = list()
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            
            if b_idx in target_lines:
                pt_type = retType(this_line)
                pt_indent = retIndent(this_line)
                
                this_indent = retIndent(this_line)
                   
                new_body.append([this_line, ''])
                new_body.append([f'{this_indent}global.set $wade{pt_type}\n', 'ConstantGlobal'])
                new_body.append([f'{this_indent}global.get $wade{pt_type}\n', 'ConstantGlobal'])

            else:
                new_body.append([this_line, ''])
            
        parsedSection['Function'][f].body = new_body    

def constant_value_splitting(parsedSection, alpha, beta, ratio=0):
    
    RE_CONST = re.compile(r'\b(i32|i64|f32|f64)\.const\s+(-?\d+)')

    functions = parsedSection['Function']
    
    for f in functions:

        offset_list = list()
        body = functions[f].body
        
        ## [error handler]
        if body == None:
            continue
        
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            if (".const " in this_line):
                offset_list.append(b_idx)
        if len(offset_list) == 0:
            continue
        
        iter = round(len(offset_list)*ratio)
        if iter == 0:
            iter = 1
        
        # print(xor_offset_list[0])
        # print('len:',len(xor_offset_list))
        
        target_lines = list()
        for _ in range(0,iter):
            while True:
                beta_idx = getDist(alpha,beta,len(offset_list))
                beta_idx = max(0, min(beta_idx, len(offset_list) - 1))
                # print(beta_idx)
                # print(xor_offset_list[beta_idx])
                selected_offset = offset_list[beta_idx]

                if selected_offset not in target_lines:
                    target_lines.append(selected_offset)
                    break
        
        new_body = list()
        for b_idx in range(0, len(body)):
            this_line = body[b_idx][0]
            
            if b_idx in target_lines:
                match_const = re.search(r'\b(i32|i64|f32|f64)\.const\s+(-?\d+)', this_line)
                typ, numstr = match_const.group(1), match_const.group(2)

                this_indent = retIndent(this_line)

                if typ.startswith('f'):
                    val = float(numstr)
                    if val == 0.0:
                        # 0.0 은 (-1.0, +1.0) 스킷
                        c = 1.0
                        a, b = -c, +c
                    else:
                        # 원본 값의 10%~90% 비율로 쪼개기
                        ratio = random.uniform(0.1, 0.9)
                        a = ratio * val
                        b = val - a

                    astr = str(a)
                    bstr = str(b)

                else:
                    val = int(numstr)
                    if val <= 1:
                        # 0 또는 1 은 음수+양수 스킷: a=-c, b=val+c
                        c = random.randint(1, max(val, 1))
                        a = -c
                        b = val + c
                    else:
                        # 1 < val: 1..val-1 사이에서 랜덤 분할
                        a = random.randint(1, val - 1)
                        b = val - a

                    astr = str(a)
                    bstr = str(b)

                new_body.append([f'{this_indent}{typ}.const {astr}\n', 'ConstantSplitting'])
                new_body.append([f'{this_indent}{typ}.const {bstr}\n', 'ConstantSplitting'])
                new_body.append([f'{this_indent}{typ}.add\n', 'ConstantSplitting'])

            else:
                new_body.append([this_line, ''])
            
        parsedSection['Function'][f].body = new_body   

def opaque_predicate_insertion(parsedSection, alpha, beta, ratio):

    current_dir = os.path.dirname(__file__)
    predicate_path = os.path.join(current_dir, "data", "opaque_predicate")
    with open(predicate_path, 'r') as fr:
        predicate = fr.readlines()

    RE_BLOCK_START = re.compile(r'^\s*\(?(block|loop|if)\b')
    RE_BLOCK_END   = re.compile(r'^\s*end\b')

    functions = parsedSection['Function']

    for f in functions:
        # print(f)
        function = parsedSection['Function'][f]
        if function.body == None:
            continue
        
        body = function.body

        offset_list = list()
        stack = []   # (block_type, start_line)
        blocks = []  # (start_line, end_line, block_type)

        for offset, code in enumerate(body):
            # print(code)
            # if not any (kw in code[0] for kw in ('block', 'if', 'end', 'else', ')')):
            #     offset_list.append(offset)

            if RE_BLOCK_START.search(code[0]):
            # block_type = m.group(1)
                stack.append((offset+1))
            elif RE_BLOCK_END.search(code[0]):
                if not stack:
                    continue
                start_offset = stack.pop()
                blocks.append([start_offset,offset-1])
            elif code[0].strip() == 'else':
                if not stack:
                    continue
                start_offset = stack.pop()
                blocks.append([start_offset,offset-1])
                stack.append((offset+1))

        if len(blocks) == 0:
            continue
            
        iter = round(len(blocks)*ratio)
        if iter == 0:
            iter = 1
        
        selected_offset_list = list()
        selected_block_list = list()
        for _ in range(iter):
            while True:
                beta_idx = getDist(alpha, beta, len(blocks))
                beta_idx = max(0, min(beta_idx, len(blocks) - 1))
                selected_block = blocks[beta_idx]

                if selected_block not in selected_block_list:
                    selected_block_list.append(selected_block)

                    full_offset = list(range(selected_block[0], selected_block[1] + 1))
                    beta_idx = getDist(alpha, beta, len(full_offset))
                    beta_idx = max(0, min(beta_idx, len(full_offset) - 1))
                    selected_offset = full_offset[beta_idx]
                    selected_offset_list.append(selected_offset)
                    break

        
        new_body = list()
        for offset in range(len(body)):
            if offset == 0:
                new_body.append([f'    i32.const 1\n    local.set $wadelocal\n','OpaquePredicateInsertion'])
            new_body.append(body[offset])
            if offset in selected_offset_list:
                body_line = body[offset][0]
                indent = retIndent(body_line)
                if RE_BLOCK_START.search(body_line) or body_line.strip()=='else':
                    indent = indent+'  '
                for p in predicate:
                    new_body.append([f'{indent}{p}','OpaquePredicateInsertion'])

        old_header = function.header
        new_header = list()
        new_header.append([old_header[0][0].strip()+' (local $wadelocal i32)\n',''])
        if len(old_header) > 1:
            for i in range(1,len(old_header)):
                new_header.append(old_header[i])
        # print(new_header)

        parsedSection['Function'][f].body = new_body
        parsedSection['Function'][f].header = new_header