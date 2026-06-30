from dataclasses import dataclass

@dataclass
class sectionOffset:
    identifier:str = None
    startOffset:int = None
    bodyStartOffset:int = None
    endOffset:int = None

@dataclass
class TYPE:
    # ID:str = None
    param:list = None
    result:list = None
    line:str = None
    
@dataclass
class IMPORT:
    # ID:str = None
    type:str = None
    name:str = None
    line:str = None
    
@dataclass
class FUNCTION:
    type:str = None
    param:list = None
    result:list = None
    local:list = None
    header:list = None
    body:list = None
    
@dataclass
class GLOBAL:
    type:str = None
    value:int = None
    line:str = None
    
@dataclass
class EXPORT:
    funcID:str = None
    line:str = None
    
@dataclass
class ELEMENT:
    line:str = None

@dataclass
class DATA:
    offset:int = None
    length:int = None
    data:bytes = None
    line:str = None

##추가
@dataclass
class TABLE:
    minSize:int = None
    maxSize:int = None
    refType:int = None
    line:str = None

@dataclass
class MEMORY:
    minSize:int = None
    maxSize:int = None
    line:str = None

@dataclass
class START:
    line:str = None

