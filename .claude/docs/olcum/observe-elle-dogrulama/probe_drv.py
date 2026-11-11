import re,subprocess,sys,json,time,collections
D=".claude/docs/olcum/observe-elle-dogrulama/"
js=open("/private/tmp/claude-501/probe.js").read()
def C(*a): return subprocess.run(["node","bin/cdpilot.js",*a],capture_output=True,text=True,timeout=90).stdout
for name,url in json.loads(sys.argv[1]):
    C("go",url); time.sleep(5)
    raw=C("eval",js).strip()
    open(D+name+"-dom.json","w").write(raw)
    ince=json.loads(C("agent","observe"))["actions"]
    full=json.loads(C("agent","observe","--full"))["actions"]
    dom=json.loads(raw)
    N=lambda x:re.sub(r"\s+"," ",x.replace("\xa0"," ")).strip().lower()[:25]
    def unm(acts):
        names=collections.Counter(N(a["name"]) for a in acts)
        fr=sum(1 for a in acts if a["role"] in ("textbox","checkbox","radio","spinbutton","combobox","slider","searchbox","switch","listbox"))
        used=collections.Counter();u=[];nf=0
        for e in dom:
            if e["tag"] in ("INPUT","TEXTAREA","SELECT") and e["role"]=="":
                nf+=1
                if nf<=fr: continue
            k=N(e["name"]);used[k]+=1
            if used[k]>names[k]: u.append(e)
        return u
    ui=unm(ince);uf=unm(full)
    fk=collections.Counter((e["tag"],N(e["name"]),e["href"]) for e in uf)
    lost=[]
    for e in ui:
        k=(e["tag"],N(e["name"]),e["href"])
        if fk[k]>0: fk[k]-=1
        else: lost.append(e)
    print(name,"dom",len(dom),"ince",len(ince),"tam",len(full),"ince-karsilanmayan",len(ui),"tam-karsilanmayan",len(uf),"INCEYE-OZGU-KAYIP",len(lost))
    for e in lost[:30]: print("   ",e["k"],e["tag"],e["role"],repr(e["name"][:40]),e["href"][:30])
    json.dump({"dom":len(dom),"ince_unm":ui,"tam_unm":uf,"lost":lost},open(D+name+"-kayip-adaylari.json","w"),ensure_ascii=False)
