import json,sys,collections
D=".claude/docs/olcum/observe-elle-dogrulama/"
out={}
for n in sys.argv[1:]:
    i=json.load(open(D+n+"-ince.json"))["actions"]; f=json.load(open(D+n+"-tam.json"))["actions"]
    ci=collections.Counter((a["role"],a["name"]) for a in i)
    seen=collections.Counter(); drop=[]
    for a in f:
        k=(a["role"],a["name"]); seen[k]+=1
        if seen[k]>ci[k]: drop.append(a)
    cf=collections.Counter((a["role"],a["name"]) for a in f)
    extra=sum(max(0,ci[k]-cf[k]) for k in ci)
    c=collections.Counter(a["role"] for a in drop)
    print("==",n,len(i),len(f),len(drop),"ince-fazla",extra,dict(c))
    json.dump(drop,open("/private/tmp/claude-501/drop-"+n+".json","w"),ensure_ascii=False)
