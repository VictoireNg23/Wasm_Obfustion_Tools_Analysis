import re
import subprocess as sp
import os
import sys
from collections import OrderedDict
import codecs

def insert_after_key(od, after_key, new_key, new_value):
    keys = list(od.keys())
    idx = keys.index(after_key) + 1

    items = list(od.items())
    items.insert(idx, (new_key, new_value))

    od.clear()
    od.update(items)


# RE_TYPE = re.compile("\s+\(type\s(.*)\s")
RE_TYPE = re.compile(
    r'^\s*\(type\s+(?P<id>\$\w+)\s+\(func'
    r'(?:\s+\(param\s+(?P<params>[^\)]+)\))?'
    r'(?:\s+\(result\s+(?P<results>[^\)]+)\))?'
    r'\s*\)\)')

# RE_IMPORT = re.compile('\s+\(import ".*"\s"(.*)"')
# RE_IMPORT = re.compile(r'^\s*\(import\s+"env"\s+"(?P<import_name>[^"]+)"\s+\((?P<type>func|global|memory|table)\s+(?P<id>[^\s\)]+)')
#                     #    ,re.MULTILINE
RE_IMPORT = re.compile(
    r'''^\s*                            
        \(import\s+                     
        "[^"]+"\s+                      
        "(?P<import_name>[^"]+)"\s+     
        \((?P<type>func|global|memory|table)\s+  
        (?P<id>[^\s\)]+)               
    ''', re.VERBOSE
)

# RE_FUNCTION = re.compile("\s+\(func\s+\((.[^\)]+)\)")
# RE_FUNCTION_1 = re.compile("\s+\(func \([^;]*;([0-9]*);\) \(type ([0-9]*)\)")
RE_FUNCTION = re.compile(r'^\s*\(func\s+(\$[^\s\(\)]+)\s+\(type\s+(\$[^\s\(\)]+)\)')
# RE_FUNCTION_2 = re.compile("\s+\(func (\$[^\s]*) \(type ([0-9]*)\)")

RE_TABLE = re.compile(
    r"""^\s*\(table\s+
        (?:(?P<id>\$\w+)\s+)?(?P<min_size>\d+)\s+
        (?:(?P<max_size>\d+)\s+)?
        (?P<ref_type>\w+)\s*
        \)""", re.VERBOSE)

RE_GLOBAL = re.compile(
    r'^\s*\(global\s+'
    r'(?:(?P<id>\$\w+)\s+)?'                           
    r'(?:(\((?P<mut>mut)\s+(?P<type>\w+)\))|(?P<init_type>\w+))\s+'  
    r'\((?P<init_op>\w+\.\w+)\s+(?P<value>[^)]+)\)\s*' 
    r'\)'
)
# RE_GLOBAL = re.compile(r'^\s*\(global\s+(?P<id>\$\w+)')

# RE_EXPORT = re.compile(r'^\s*\(export\s+"(?P<id>[^"]+)"\s+\(func\s+(?P<funcName>\$\w+)\)\)')
import re

RE_EXPORT = re.compile(r'''
    ^\s*                            
    \(export\s+                     
      "(?P<id>[^"]+)"\s+   
      \(
        (?P<kind>func|memory|table|global|tag)  # func/memory/table/global/tag
        \s+
        (?P<funcName>\$[^\s\)]+)        
      \)
    ''', re.VERBOSE)

# RE_ELEM = re.compile("\s+\(elem\s+\(;(\d+);")
RE_ELEM = re.compile(r'^\s*\(elem\s+(?P<id>\$\w+)')

RE_DATA = re.compile(
    r'^\s*\(data\s+(?P<id>\$[\w.]+)\s+\(i32\.const\s+(?P<offset>\d+)\)\s+"(?P<data>.*?)"\)',
    re.DOTALL
)
# RE_DATA = re.compile("\s+\(data\s+\(;(\d+);")

## 추가
RE_MEMORY = re.compile(
    r'^\s*\(memory\s+(?:(?P<id>\$\w+)\s+)?(?P<min_size>\d+)(?:\s+(?P<max_size>\d+))?\s*\)')
# RE_MEMORY = re.compile(r"\s+\(memory\s+\(;(\d+);\).*")
# RE_TABLE = re.compile(r"\s+\(table\s+\(;(\d+);\).*")

# RE_PARAM = re.compile('\(param (([if][3264]{1,2}( )*)+)\)')
# RE_LOCAL = re.compile('\(local (([if][3264]{1,2}( )*)+)\)')
# RE_RESULT = re.compile('\(result (([if][3264]{1,2}( )*)+)\)')
RE_PARAM = re.compile(r'\(param((?:\s+\$\w+)+)\s+([if][3264]{1,2})\)')
RE_LOCAL = re.compile(r'\(local((?:\s+\$\w+)+)\s+([if][3264]{1,2})\)')
RE_RESULT = re.compile(r'\(result\s+([if][3264]{1,2})\)')

#from wasmParser 
from . import sectionStructure as ss
from strategies import state

## 테스트용
from importlib import reload
reload(ss)

# print('__file__={0:<35} | __name__={1:<25} | __package__={2:<25}'.format(__file__,__name__,str(__package__)))

def retIndent(inst):
    return ' '*(len(inst) - len(inst.lstrip()))

def retType(inst):
    if "i32" in inst:
        return "i32"
    elif "i64" in inst:
        return "i64"
    elif "f32" in inst:
        return "f32"
    elif "f64" in inst:
        return "f64"

def parse_param_local_blocks(code, regex):
    results = []
    for match in regex.finditer(code):
        id_block = match.group(1)
        type_str = match.group(2)
        ids = id_block.strip().split()
        for _ in ids:
            results.append(type_str)
    return results

def parseWast(origin_wast):
    parsedSection = {'Type': OrderedDict(), 'Import': OrderedDict(),'Function': OrderedDict(), 'Table': OrderedDict(), 'Memory': OrderedDict(), 'Global': OrderedDict(), \
        'Export': OrderedDict(), 'Start': OrderedDict(), 'Element': OrderedDict(), 'Data': OrderedDict()}

    # funcHeaderLine = str()
    funcHeaderArea = False
    funcHeaderLine = list()
    funcBodyArea = False
    funcBodyLine = list()
    func_bracketNum = 0


    for l in range (0, len(origin_wast)):
        
        line = origin_wast[l]
        
        ## Type, Import, Function, Table, Memory, Global, Export, Start, Element, Code, Data, Custom
        ## 특정 section을 시작하는 line은 1로 수정
        whichSection = [0 for i in range(12)]
        
        # print(line)
        matchType = re.search(RE_TYPE,line)
        if matchType:
            # print(matchType.group(1))
            ID = matchType.group("id")
            params = matchType.group("params").split() if matchType.group("params") else None
            results = matchType.group("results").split() if matchType.group("results") else None

            whichSection[0] = 1
            
            # has_param = re.search(RE_PARAM,line)
            # param = has_param.group(1) if has_param is not None else None
            # has_result = re.search(RE_RESULT,line)
            # result = has_result.group(1) if has_result is not None else None

            # TYPE - param:list, result:list, line:str
            parsedSection["Type"][ID] = ss.TYPE(param=params, result=results, line=[line, ''])
        
        matchImport = re.search(RE_IMPORT,line)
        if matchImport:
            importType = matchImport.group("type")
            importID = matchImport.group("id")
            importName = matchImport.group("import_name")
            whichSection[1] = 1
            
            # isFuncImport = re.search(RE_FUNCTION_1,line)
            # if not isFuncImport:
            #     isFuncImport = re.search(RE_FUNCTION_2,line)
            # if isFuncImport:
            #     funcID = isFuncImport.group(1) ##function ID. e.g., ;1;
            #     funcType = isFuncImport.group(2)
            # else:
            #     funcID = None
            #     funcType = None
            parsedSection["Import"][importID] = ss.IMPORT(
                # ID=importID, 
                type=importType, 
                name=importName,
                line=[line, ''])
            # parsedSection["Import"][importID] = ss.IMPORT(funcID=funcID, type=funcType, line=[line, ''])
            # parsedSection["Import"].append(ss.sectionOffset(identifier=importID, startOffset=l))

        matchMemory = re.match(RE_MEMORY, line)
        if matchMemory:
            memID = matchMemory.group('id')
            minSize = int(matchMemory.group('min_size')) if matchMemory.group('min_size') is not None else None
            maxSize = int(matchMemory.group('max_size')) if matchMemory.group('max_size') is not None else None
            whichSection[4] = 1
            parsedSection['Memory'][memID] = ss.MEMORY(minSize=minSize, maxSize=maxSize, line=[line, ''])  # 또는 ss.MEMORY if 따로 정의했다면

        matchTable = re.search(RE_TABLE, line)
        if matchTable:
            tableID = matchTable.group('id')
            minSize = int(matchTable.group('min_size')) if matchTable.group('min_size') is not None else None
            maxSize = int(matchTable.group('max_size')) if matchTable.group('max_size') is not None else None
            refType = matchTable.group('ref_type')
            whichSection[3] = 1
            parsedSection['Table'][tableID] = ss.TABLE(minSize=minSize, maxSize=maxSize, refType=refType, line=[line, ''])  # 또는 ss.TABLE if 따로 정의했다면

        matchGlobal = re.search(RE_GLOBAL,line)
        if matchGlobal:
            globalID = matchGlobal.group('id')
            type = matchGlobal.group('type')
            value = matchGlobal.group('value')
            whichSection[5] = 1
            
            # [TY] value가 env문자열일 수도 있음
            parsedSection["Global"][globalID] = ss.GLOBAL(type=type, value=value, line=[line, ''])
            # print(globalID)
            # parsedSection["Global"].append(ss.sectionOffset(identifier=globalID.replace(';',''), startOffset=l))
        
        matchExport = re.search(RE_EXPORT,line)
        if matchExport:
            exportID = matchExport.group('id')
            funcName = matchExport.group('funcName')
            whichSection[6] = 1
            # raw_line = line.replace(exportID,'')
            if line.count(')') - line.count('(') > 0:
                line = line.rstrip().rsplit(')', 1)[0]+'\n'
            parsedSection["Export"][exportID] = ss.EXPORT(funcID=funcName, line=[line, ''])
            
        matchElem = re.search(RE_ELEM,line)
        if matchElem:
            elemID = matchElem.group('id')
            whichSection[8] = 1
            if line.count(')') - line.count('(') > 0:
                line = line.rstrip().rsplit(')', 1)[0]+'\n'
            parsedSection["Element"][elemID] = ss.ELEMENT(line=[line, ''])
            
        matchData = re.search(RE_DATA,line)
        if matchData:
            dataID = matchData.group('id')
            offset = int(matchData.group('offset'))
            data_str = matchData.group('data')

            decoded_data = codecs.decode(data_str, 'unicode_escape').encode('latin1')
            length = len(decoded_data)
            whichSection[10] = 1

            raw_line = line.replace(data_str,'')
            if raw_line.count(')') - raw_line.count('(') == 1:
                line = line.rstrip().rsplit(')', 1)[0]+'\n'
            parsedSection["Data"][dataID] = ss.DATA(offset=offset, data=decoded_data, length=length, line=[line, ''])
        
        # matchFunc = re.match(RE_FUNCTION_1,line)
        # if not matchFunc:
        matchFunc = re.match(RE_FUNCTION,line)
        if matchFunc:
            # print('function')
            # print(matchType.group(1))
            funcID = matchFunc.group(1) ##function ID. e.g., ;1;
            funcType = matchFunc.group(2)
            whichSection[2] = 1
            # print(funcID)
            func_bracketNum += line.count('(') - line.count(')')
            
            funcHeaderArea = True ##function header line이 여러개인 경우, payload와 분류하기 위해
            funcHeaderLine.append([line, ''])
            
            parsedSection["Function"][funcID] = ss.FUNCTION(type=funcType)
        
            
        # print(whichSection)
        if 1 not in whichSection and (funcHeaderArea==True or funcBodyArea==True):
            
            func_bracketNum += line.count('(') - line.count(')')
            
            # print(l, func_bracketNum)
            if func_bracketNum == 1:
                # print('\n', line.strip())
                if (((line.count('(')+line.count(')')) == 0) or 'block' in line) and funcBodyArea == False:
                    # print('here')
                    funcHeaderArea = False
                    
                    funcBodyArea = True
                    funcBodyLine.append([line, ''])
                    
                    # thisFuncElem = parsedSection["Function"][len(parsedSection["Function"])-1]
                    # thisFuncElem.bodyStartOffset = l
                    # parsedSection["Function"][len(parsedSection["Function"])-1] = thisFuncElem
                    
                elif funcBodyArea == False:
                    funcHeaderLine.append([line, ''])
                    
                else:
                    funcBodyLine.append([line, ''])
                    continue
            elif func_bracketNum == 0:
                # thisFuncElem = parsedSection["Function"][len(parsedSection["Function"])-1]
                # thisFuncElem.endOffset = l
                # if thisFuncElem.bodyStartOffset == None:
                #     thisFuncElem.bodyStartOffset = (l-1)
                
                # parsedSection["Function"][len(parsedSection["Function"])-1] = thisFuncElem
                funcHeaderLineStr = [h[0] for h in funcHeaderLine]
                # print(funcHeaderLineStr)
                funcHeaderStr = (''.join([n.strip() for n in funcHeaderLineStr]))
                # print(funcHeaderStr)
                # print(funcID, funcHeaderStr, '\n')
                
                # has_param = re.search(RE_PARAM,funcHeaderStr)
                # param = has_param.group(1) if has_param is not None else None
                params = parse_param_local_blocks(funcHeaderStr, RE_PARAM)
                locals = parse_param_local_blocks(funcHeaderStr, RE_LOCAL)

                has_result = re.search(RE_RESULT, funcHeaderStr)
                result = has_result.group(1) if has_result is not None else None
                
                # has_local = re.search(RE_LOCAL,funcHeaderStr)
                # local = has_local.group(1) if has_local is not None else None      
                
                parsedSection["Function"][funcID].param = params
                parsedSection["Function"][funcID].result = result
                parsedSection["Function"][funcID].local = locals
                parsedSection["Function"][funcID].header = funcHeaderLine
                funcHeaderLine = list()
                
                last_bodyIndent = retIndent(line)
                # if line[-2] == ')' and (line != last_bodyIndent+'end)\n'):
                if line[-2] == ')':
                    last_bodyLine = [[line[:-2]+'\n', ''], [last_bodyIndent+')\n','']]
                else:
                    last_bodyLine = [[line, '']]
                
                # funcBodyLine.append(line)
                funcBodyLine += last_bodyLine
                parsedSection["Function"][funcID].body = funcBodyLine
                
                funcBodyArea = False
                funcBodyLine = list()
    
    # print(parsedSection["Global"])          
    # print(state.LAST_GLOBAL_ID)
    
    return parsedSection


def savePertWasm(path, name, ptSection):
    # print(path)
    os.makedirs(path+"meta/", exist_ok=True)
    
    with open(path+name, 'w') as fw, open(path+'meta/'+name, 'w') as mw:
        fw.write("(module\n")
        
        for sec in ptSection:
            
            if sec=="Type":
                sec_type = ptSection["Type"]
                if len(sec_type)!=0:
                    for t in sec_type:
                        fw.write(sec_type[t].line[0])
                        if sec_type[t].line[1] != '':
                            mw.write(f'[TYPE]{t}, {sec_type[t].line[1]}\n')
            
            elif sec=="Import":
                # print('import')
                sec_import = ptSection["Import"]
                if len(sec_import)!=0:
                    for i in sec_import:
                        fw.write(sec_import[i].line[0])
                        if sec_import[i].line[1] != '':
                            mw.write(f'[IMPORT]{i}, {sec_import[i].line[1]}\n')
                        
            elif sec=="Function":
                # print('here?')
                sec_function = ptSection["Function"]
                if len(sec_function)!=0:
                    for f in sec_function:
                        ## [error handler]
                        if sec_function[f].header == None:
                            continue

                        headerLines = [h[0] for h in sec_function[f].header]
                        fw.write(''.join(headerLines))
                        for h_idx in range(0, len(headerLines)):
                            if sec_function[f].header[h_idx][1] != '':
                                mw.write(f'[FUNC-H]{f}-{h_idx}, {sec_function[f].header[h_idx][1]}\n')
                        
                        bodyLines = [b[0] for b in sec_function[f].body]
                        # if bodyLines[-1]=='    )\n':
                        #     bodyLines.remove('    )\n')
                        #     funcEndLine = bodyLines[-1]
                        #     bodyLines[-1] = funcEndLine.replace('\n',')\n')
                            # print(sec_function[f].body[-1])
                        for b_idx in range(0, len(bodyLines)):
                            # print(sec_function[f].body[b_idx])
                            if sec_function[f].body[b_idx][1] != '':
                                mw.write(f'[FUNC-B]{f}-{b_idx}, {sec_function[f].body[b_idx][1]}\n')
                        fw.write(''.join(bodyLines))
            
            elif sec=="Table":
                sec_table = ptSection["Table"]
                if len(sec_table)!=0:
                    next
                for f in sec_table:
                    fw.write(''.join(sec_table[f].line[0]))
            
            elif sec=="Memory":
                sec_memory = ptSection["Memory"]
                if len(sec_memory)!=0:
                    # next
                    for f in sec_memory:
                        fw.write(''.join(sec_memory[f].line[0]))
                        # fw.write(''.join(sec_function[f].body))
                    
            elif sec=="Global":
                sec_global = ptSection["Global"]
                if len(sec_global)!=0:
                    for g in sec_global:
                        fw.write(sec_global[g].line[0])
                        if sec_global[g].line[1] != '':
                            mw.write(f'[GLOBAL]{g}, {sec_global[g].line[1]}\n')
                        
            elif sec=="Export":
                # print('here)')
                sec_export = ptSection["Export"]
                if len(sec_export)!=0:
                    for x in sec_export:
                        fw.write(sec_export[x].line[0])
                        if sec_export[x].line[1] != '':
                            mw.write(f'[EXPORT]{x}, {sec_export[x].line[1]}\n')
                        
            elif sec=="Start":
                sec_start = ptSection["Start"]
                if len(sec_start)!=0:
                    # print('here')
                    for s in sec_start:
                        fw.write(sec_start[s].line[0])
                    
            elif sec=="Element":
                sec_element = ptSection["Element"]
                if len(sec_element)!=0:
                    for e in sec_element:
                        # print(sec_element[e].line[0])
                        fw.write(sec_element[e].line[0])
                        # if sec_element[e].line[1] != '':
                        #     mw.write(f'[ELEMENT]{e}, {sec_element[e].line[1]}')
                        
            elif sec=="Code":
                sec_code = ptSection["Code"]
                if len(sec_code)!=0:
                    next
                    
            elif sec=="Data":
                # continue
                sec_data = ptSection["Data"]
                if len(sec_data)!=0:
                    for d in sec_data:
                        fw.write(sec_data[d].line[0])
                        if sec_data[d].line[1] != '':
                            mw.write(f'[DATA]{d}, {sec_data[d].line[1]}')
                        
            # elif sec=="Custom":
            #     sec_custom = ptSection["Custom"]
            #     if len(sec_custom)!=0:
            #         next
        fw.write(')')


    cmd = "wat2wasm " + path+name + " -o " + path+(name[:-1] + 'm')
    # print(cmd)
    result = sp.run(cmd.split(' '))
    if result.returncode != 0:
        print("[wat2wasm failed]", path)
    
    # with open(path, 'w') as fw:
    #     for offset in range (0,len(wast)):
    #         for line in wast[offset]:
    #             fw.write(line)
    
##################################################################


def retFuncIDs(parsedSection):
    
    funcIDs = list()
    
    for f in parsedSection['Function']:
        funcIDs.append(f.identifier)
    
    return funcIDs