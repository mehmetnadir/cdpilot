import subprocess,sys,os,time,json
D=".claude/docs/olcum/observe-elle-dogrulama/"
def C(*a):
    r=subprocess.run(["node","bin/cdpilot.js",*a],capture_output=True,text=True,timeout=90)
    return r.stdout
sites=json.loads(sys.argv[1])
for name,url in sites:
    C("go",url); time.sleep(4)
    href=C("eval","location.href").strip()
    a=C("agent","observe"); a2=C("agent","observe"); f=C("agent","observe","--full")
    open(D+name+"-ince.json","w").write(a); open(D+name+"-ince2.json","w").write(a2); open(D+name+"-tam.json","w").write(f)
    try:
        ja,ja2,jf=[json.loads(x)["actions"] for x in (a,a2,f)]
        print(name,href[:60],len(ja),len(ja2),len(jf),"same2=",ja==ja2)
    except Exception as e: print(name,"ERR",e,a[:200])
