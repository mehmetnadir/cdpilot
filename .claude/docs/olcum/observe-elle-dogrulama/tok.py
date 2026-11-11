import json,collections,tiktoken
e=tiktoken.get_encoding("o200k_base")
D=".claude/docs/olcum/observe-elle-dogrulama/"
C={"heading","navigation","sectionheader","region","columnheader"}
rows=[]
for n in ["hn","hn-yorum","hn-yorum2","excalidraw","wikipedia","github","httpbin","mdn"]:
    ti=len(e.encode(open(D+n+"-ince.json").read().strip())); tf=len(e.encode(open(D+n+"-tam.json").read().strip()))
    i=json.load(open(D+n+"-ince.json"))["actions"]; f=json.load(open(D+n+"-tam.json"))["actions"]
    ci=collections.Counter((a["role"],a["name"]) for a in i); seen=collections.Counter(); drop=[]
    for a in f:
        k=(a["role"],a["name"]); seen[k]+=1
        if seen[k]>ci[k]: drop.append(a)
    c=sum(1 for a in drop if a["role"] in C); b=len(drop)-c
    k=json.load(open(D+n+"-kayip-adaylari.json"))
    print(n,len(i),len(f),ti,tf,"%.0f%%"%(100*(1-ti/tf)),"drop",len(drop),"A0 B",b,"C",c,"lost",len(k["lost"]),"dom",k["dom"])
