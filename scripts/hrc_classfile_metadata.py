"""Small JVM classfile metadata parser; does not execute inspected classes."""
import struct

def native_methods(blob):
    pos=8
    def u2():
        nonlocal pos
        n=struct.unpack_from('>H',blob,pos)[0];pos+=2;return n
    count=u2();cp=[None]*count;i=1
    while i<count:
        tag=blob[pos];pos+=1
        if tag==1:
            n=u2();cp[i]=blob[pos:pos+n].decode('utf-8','replace');pos+=n
        elif tag in (3,4):pos+=4
        elif tag in (5,6):pos+=8;i+=1
        elif tag in (7,8,16,19,20):pos+=2
        elif tag in (9,10,11,12,17,18):pos+=4
        elif tag==15:pos+=3
        else:raise ValueError(tag)
        i+=1
    pos+=6
    interfaces=u2();pos+=interfaces*2
    def skip_attributes():
        nonlocal pos
        for _ in range(u2()):
            pos+=2
            n=struct.unpack_from('>I',blob,pos)[0];pos+=4+n
    for _ in range(u2()):
        pos+=6;skip_attributes()
    out=[]
    for _ in range(u2()):
        access,name,desc=u2(),u2(),u2()
        if access&0x100:out.append({'name':cp[name],'descriptor':cp[desc],'access':access})
        skip_attributes()
    return out
