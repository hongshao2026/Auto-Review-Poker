"""Read-only Brotli schema validation; complete decoded table lives only in RAM.

Writes metadata and a small, deterministic numeric test vector for an isolated
original oh/ol comparison. No target application classes are executed here.
"""
from itertools import combinations, permutations
from pathlib import Path
import array, hashlib, json, struct, subprocess, sys, zipfile
from hrc_classfile_metadata import native_methods

WORKSPACE=Path(__file__).resolve().parents[1]
ROOT=WORKSPACE/'analysis/hrc-deep/equity'
ROOT.mkdir(parents=True,exist_ok=True)
JDK=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
PLUGINS=Path(r'D:\Program Files\HRC\plugins')
DEC=PLUGINS/'net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar'
EC=PLUGINS/'org.eclipse.collections_11.1.0.v20220705-1455.jar'
JAR=PLUGINS/'net.holdemresources.postflopabstractions.holdem_1.0.0.jar'
MEMBER='abstractions/Johanson13_2021-02/Johanson13_2021-02.64.1.5c50391a2dffc81287be70955ad7a86f9f607745f6a1a8f96af159d51db2e22d.dat.br'
MASK=0x1111111111111
def canonical(cards):
    return sum(v<<i for i,v in enumerate(sorted((cards>>s)&MASK for s in range(4))))
def permute(cards, perm):
    return sum(((cards>>s)&MASK)<<perm[s] for s in range(4))
def combo_index(mask):
    cards=[c for c in range(52) if mask>>c&1]
    return cards[1]*(cards[1]-1)//2+cards[0]

subprocess.run([str(JDK/'javac.exe'),'-cp',str(DEC),'-d',str(ROOT),str(WORKSPACE/'scripts/java/BrotliResourceBytes.java')],check=True,capture_output=True)
raw=subprocess.run([str(JDK/'java.exe'),'-Xmx256m','-cp',str(ROOT)+';'+str(DEC),'BrotliResourceBytes',str(JAR),MEMBER],check=True,capture_output=True).stdout
digest=hashlib.sha256(raw).hexdigest()
assert digest==MEMBER.split('.')[-3]
boards=sorted({canonical(sum(1<<c for c in cards)) for cards in combinations(range(52),3)})
assert len(boards)==1755 and len(raw)==len(boards)*1176*2
values=array.array('h'); values.frombytes(raw)
if sys.byteorder!='little': values.byteswap()
assert min(values)>=0 and max(values)<64
holes=[(1<<hi)|(1<<lo) for hi in range(52) for lo in range(hi)]
cases=[]
for row in (0,1,15,111,700,1000,1500,1754):
    board=boards[row]
    legal=[h for h in holes if not h&board]
    for slot in (0,1,17,256,800,1175):
        hole=legal[slot]; bucket=values[row*1176+slot]
        for perm_id,perm in enumerate(permutations(range(4))):
            b=permute(board,perm); h=permute(hole,perm)
            # Equal suit masks can permute holes within a board stabilizer;
            # verify expected value with the independent stable suit ordering.
            sorted_suits=sorted(range(4),key=lambda s:(b>>s)&MASK)
            canonical_perm=[sorted_suits.index(s) for s in range(4)]
            canonical_hole=permute(h,canonical_perm)
            canonical_slot=legal.index(canonical_hole)
            actual_expected=values[row*1176+canonical_slot]
            assert actual_expected==bucket, 'resource breaks board suit symmetry'
            cases.append((f'row{row}_hole{slot}_perm{perm_id}',b,combo_index(h),bucket))
(ROOT/'flop64-probe-cases.tsv').write_text(''.join('\t'.join(map(str,c))+'\n' for c in cases),encoding='utf-8')
deps=[]
for dependency in (DEC,EC):
    natives=[]; resources=[];count=0
    with zipfile.ZipFile(dependency) as z:
        for member in z.infolist():
            if member.filename.endswith('.class'):
                count+=1
                methods=native_methods(z.read(member))
                if methods:natives.append({'member':member.filename,'methods':methods})
            elif member.filename.lower().endswith(('.dll','.so','.dylib')):resources.append(member.filename)
    deps.append({'jar':str(dependency),'sha256':hashlib.sha256(dependency.read_bytes()).hexdigest(),'classes':count,'native_methods':natives,'native_resources':resources})
result={'scope':'Generic Brotli decode and independent schema check; no HRC application classes executed.',
        'jar':str(JAR),'member':MEMBER,'decompressed_bytes':len(raw),'sha256':digest,'filename_hash_matches':True,
        'canonical_board_count':len(boards),'canonical_board_order':'ascending 52-bit masks after sorting four rank/suit vectors',
        'canonical_board_le64_sha256':hashlib.sha256(b''.join(struct.pack('<Q',x) for x in boards)).hexdigest(),
        'row_bytes':2352,'holes_per_row':1176,'values':len(values),'minimum_bucket':min(values),'maximum_bucket':max(values),'distinct_buckets':len(set(values)),
        'fixed_board_hole_pairs':48,'suit_permutations_per_pair':24,'case_count':len(cases),'board_symmetry_sample_passed':True,
        'original_reader_executed':False,'dependencies':deps}
(ROOT/'flop64-resource-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
