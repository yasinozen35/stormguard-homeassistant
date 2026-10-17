# StormGuard for Home Assistant

[Türkçe](#türkçe) · [English](#english)

> **Uygulama olayı yayınlar, cihaz durumunu Home Assistant yönetir.**
> *The app publishes events; Home Assistant manages device state.*

---

## Türkçe

### Bu nedir?

[StormGuard](https://github.com/yasinozen35) bir hava durumu uyarı uygulamasıdır.
"Kalkan" açtığınız alanlar için (modem, araç, bitkiler, çamaşır) risk
başladığında ve bittiğinde Home Assistant'a **olay** yayınlar:

- `raised` — "elektronik için yıldırım riski başladı"
- `cleared` — "bu risk bitti"
- `test` — uygulamadaki **Test olayı gönder** düğmesi; hiçbir cihazı değiştirmez

Uygulama **komut göndermez** (`turn_off` yok) ve cihazlarınızın adını
(`entity_id`) **bilmez**. Ne yapılacağına bu depodaki şablonlar ya da sizin
otomasyonlarınız karar verir.

### Neden böyle? (motto)

Uyuyan bir telefon güvenilir şekilde ağ isteği atamaz: Android arka plan
görevlerini kısar, üretici güç yönetimi uygulamayı öldürür, tek bir ağ hatası
o pencereyi kaybettirir. Uygulama "modemi kapat / aç" komutu gönderseydi,
kaçırılan tek bir "aç" modemi kapalı **bırakırdı**.

Bu yüzden buradaki her şey şu kurala uyar: **cihazı değiştiren her otomasyon,
`cleared` gelince VEYA bir güvenlik süresi dolunca (hangisi önce olursa) cihazı
geri alır.** En kötü durum "cihaz hiç kapanmadı" olur, asla "cihaz kapalı
kaldı" değil.

### İki yol

| | **A. Şablon (blueprint)** | **B. Entegrasyon (HACS)** |
|---|---|---|
| Kurulum | Hiçbir şey kurulmaz; şablonu içe aktarın | HACS ile özel entegrasyon |
| Ne verir | Hazır otomasyon: olay → aksiyon → geri alma | 4 `binary_sensor` (kalkan başına) + "Son olay" sensörü + olay veriyolu |
| Webhook kimliği | Kendiniz uydurursunuz / uygulama üretir | Entegrasyon üretir, **eşleştirme bağlantısı** gösterir |
| HA yeniden başlarsa | Kalan süre beklenir (ayrıntı aşağıda) | Durum ve süreler tamamen geri yüklenir |
| Kime | Tek bir priz/kapı için hızlı kurulum | Kendi otomasyonlarını yazanlar, panolar |

**Aynı webhook kimliğinde ikisini birlikte kullanmayın** (aşağıya bakın).

### Tek webhook kimliği — nasıl çalışıyor?

Uygulama **tek** bir webhook kimliğine yayın yapar. Kalkan başına ayrı kimlik
yoktur ve gerekmez:

- **Yol A:** Home Assistant'ın webhook tetikleyicisi **aynı kimliği birden çok
  otomasyonun paylaşmasına izin verir** (HA 2022.9'dan beri; HA kaynağında
  `webhook/trigger.py` her kimlik için bir tetikleyici *listesi* tutar ve gelen
  her isteği listedeki herkese iletir). Yani "Prizi kapat" (elektronik) ve
  "Kapıyı kapat" (araç) şablonlarından birer otomasyon oluşturup **ikisine de
  aynı kimliği** yazarsınız; her biri yalnızca kendi kalkanının olaylarına
  tepki verir. Bu, testlerde gerçek bir HA içinde doğrulanır
  (`test_two_blueprints_share_one_webhook_id`).
  - Kimliği paylaşan bütün otomasyonlarda **"Yalnızca ev ağından kabul et"
    ayarını aynı seçin**: HA, kimliği ilk kaydeden otomasyonun ayarını kullanır.
- **Yol B:** Entegrasyon kimliğin tek sahibidir ve olayı 4 kalkan sensörüne
  dağıtır. Otomasyonlarınız webhook'u değil sensörleri dinler.
- **İkisi aynı kimlikle olmaz:** HA bir webhook kimliğine ya otomasyon
  tetikleyicilerini ya da bir entegrasyonu bağlar. Çakışırsa entegrasyon
  kurulumu açık bir hatayla durur, kimliği otomasyondan çalmaz.

---

### Yol A — Şablon (kurulum gerektirmez)

Şablonlar (Home Assistant **2025.4** veya üstü):

| Şablon | Ne yapar | Varsayılan kalkan |
|---|---|---|
| [`switch_guard.yaml`](blueprints/automation/stormguard/switch_guard.yaml) — *Prizi kapat* | Seçilen prizleri kapatır, sonra **yalnızca kendi kapattıklarını** açar | Elektronik (yıldırım) |
| [`cover_guard.yaml`](blueprints/automation/stormguard/cover_guard.yaml) — *Kapıyı/tenteyi kapat* | Garaj kapısı/tente/panjuru kapatır, isteğe bağlı yeniden açar | Araç (dolu) |
| [`climate_guard.yaml`](blueprints/automation/stormguard/climate_guard.yaml) — *Klimaları kapat* | **Açık** klimaları kapatır, sonra **önceki ayarlarıyla** (mod, sıcaklık, fan) açar | Elektronik (yıldırım) |
| [`shield_actions.yaml`](blueprints/automation/stormguard/shield_actions.yaml) — *Kalkan aksiyonları* | Risk başlayınca / bitince **sizin seçtiğiniz** aksiyonlar | Elektronik |

1. **Şablonu içe aktarın:** Ayarlar → Otomasyonlar ve Sahneler → Şablonlar →
   **Şablonu içe aktar** → şablonun GitHub adresini yapıştırın, ör.
   `https://github.com/yasinozen35/stormguard-homeassistant/blob/main/blueprints/automation/stormguard/switch_guard.yaml`
   ([tek tıkla](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fyasinozen35%2Fstormguard-homeassistant%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fstormguard%2Fswitch_guard.yaml)).
2. **Webhook kimliği seçin.** StormGuard → Uyarılar → Akıllı Ev ekranı güçlü
   bir kimlik üretebilir (`stormguard_…`). Yalnızca harf, rakam, `_`, `-`;
   en fazla 64 karakter. Kimlik bir **sırdır**.
3. **Şablondan otomasyon oluşturun:** kimliği, kalkanı, cihazı ve güvenlik
   süresini (varsayılan 60 dk) seçin. Başka bir kalkan için aynı şablondan ya
   da diğer şablondan **ikinci bir otomasyon** oluşturup **aynı kimliği**
   yazın.
4. **Uygulamada:** sunucu adresi `http://<HA-IP>:8123` (yalnızca kök — sonuna
   `/api/webhook/…` yazmayın), aynı kimlik. **Kaydet** → **Yayın etkin**.
5. **Test olayı gönder** — hiçbir cihaz değişmez. Ulaştığını görmek için
   aşağıdaki küçük otomasyonu ekleyebilirsiniz (aynı kimliği paylaşır):

```yaml
# stormguard-example: webhook-test-notification
alias: "StormGuard — test olayı geldi"
triggers:
  - trigger: webhook
    webhook_id: stormguard_ORNEK_KIMLIK
    allowed_methods: [POST]
    local_only: true
conditions:
  - condition: template
    value_template: >-
      {{ trigger.json is defined and trigger.json.source == 'stormguard'
         and trigger.json.state == 'test' }}
actions:
  - action: persistent_notification.create
    data:
      title: StormGuard
      message: "Test olayı ulaştı: {{ trigger.json.headline }}"
```

### Klimalar (climate_guard)

Yıldırımda klimaları kapatıp fırtına geçince **eski ayarlarıyla** açar. Örn.
1× Daikin Shira Plus (Daikin Onecta) + 2× Daikin Kaira Plus (Midea) — hepsi
Home Assistant'ta `climate` varlığıdır.

- **Kapatırken:** yalnızca o an **açık** olanlar (kapalı, `unavailable`,
  `unknown` olanlara dokunmaz). Her biri için önce bir sahne anlık görüntüsü
  alınır (`scene.create`, `scene.stormguard_<otomasyon>_<klima>`), sonra
  `climate.set_hvac_mode: off`. `climate.turn_off` kullanılmaz: HA bu servisi
  yalnızca `TURN_OFF` özelliği olan varlıklara izin verir
  (`climate/services.py`, `async_register_entity_service(SERVICE_TURN_OFF, …,
  [ClimateEntityFeature.TURN_OFF])`); özelliği olmayan bir klima açıkça
  hedeflenirse çağrı hata verir. `set_hvac_mode` özellik istemez.
- **Geri açarken:** yalnızca **hâlâ kapalı** olanlar — bu sırada birini siz
  açtıysanız ona dokunmaz. Sahne varsa `scene.turn_on` (HA'nın
  `climate/reproduce_state.py`'si sırasıyla mod, sıcaklık, ön ayar, salınım,
  fan ve nemi geri yazar). Sahne yoksa kayıttaki mod → sıcaklık → fan.
- **Neden `climate.turn_on` değil:** varlık kendi açma komutunu
  uygulamıyorsa HA'nın varsayılanı sırasıyla `heat_cool`, `heat`, `cool`
  modlarından ilk desteklenenini seçer (`climate/__init__.py`,
  `ClimateEntity.async_turn_on`, "Fake turn on") — yazın ısıtma açılabilir.
- **Hafıza (önerilir):** sahneler kalıcı değildir; HA yeniden başlarsa
  silinir. Bir **Metin** yardımcısı oluşturun (Ayarlar → Cihazlar ve Hizmetler
  → Yardımcılar → Metin, **en fazla uzunluk: 255**, desen boş) ve şablonda
  *Hafıza* olarak seçin. Şablon oraya
  `d=<son tarih>;climate.salon=cool/22.5/quiet;…` yazar, geri açınca siler.
  Arayüzde oluşturulan Metin yardımcısının varsayılan sınırı **100**'dür;
  sınıra sığmazsa önce fan, sonra sıcaklık düşülür, en son yalnızca sığan
  klimalar yazılır — sınır asla aşılmaz (aşılsaydı HA değeri sessizce
  reddederdi: `input_text.async_set_value`).
  - Yeniden başlatmada süre dolmadıysa kalan süre beklenir; HA kapalıyken
    dolduysa açılışta (24 saate kadar) geri açılır; daha eskiyse kayıt
    silinir, hiçbir şey açılmaz.
  - **En kolayı: hazır paket.** [`packages/stormguard.yaml`](packages/stormguard.yaml)
    dosyasını HA'nın `config/packages/` klasörüne kopyalayın, `configuration.yaml`
    içinde paketler kapalıysa bir kez açın:
    ```yaml
    homeassistant:
      packages: !include_dir_named packages
    ```
    HA'yı yeniden başlatın; `input_text.stormguard_klima_hafiza` (en fazla
    uzunluk 255) oluşur. Şablonda *Hafıza* olarak onu seçin. Pakette bilerek
    `initial` yok: olsaydı HA her yeniden başlatmada değeri sıfırlar, hafıza tam
    ihtiyaç anında boşalırdı.
  - **Hafıza yoksa yeniden başlatmada hiçbir şey yapılmaz.** Hangi klimayı
    şablonun kapattığını bilemez; sizin kapalı tuttuğunuz bir klimayı açmak
    yanlış olur. Bu durumda HA oturum sırasında yeniden başlarsa klimalar
    kapalı kalır — bu yüzden yardımcıyı oluşturun.
- **Daikin Onecta** (HACS, bulut): Daikin bulut API'sinin günlük istek sınırı
  vardır (yaklaşık **200 istek/gün**). Bir fırtına klima başına kapatmada 1,
  açmada sahne ile 2–5 istek (mod, sıcaklık, fan, salınım…) harcar; sık
  güncelleme (polling) aralığını kısa tuttuysanız sınıra yaklaşabilirsiniz.
  Bulut erişilemezse komut başarısız olur — şablon diğer klimalarla devam eder.
- **Midea** (Kaira Plus, yerel): klimaya **sabit IP** verin (modemde DHCP
  rezervasyonu); IP değişirse varlık `unavailable` olur ve şablon onu atlar.
- `scene` entegrasyonu gerekir (`default_config` içinde vardır).

#### Şablonlar nasıl karar veriyor

- Yalnızca `source: stormguard`, seçilen kalkan, `raised`/`cleared` ve en
  düşük şiddet ve üstü (`warning` < `critical`) dikkate alınır. `test`,
  başka kalkanlar ve bilinmeyen durumlar **hiçbir şey yapmaz**.
- İlk `raised` bir **oturum** başlatır: cihaz korunur, sonra oturum aynı
  kimliği dinlemeye devam eder. Oturum, kalkanın **bütün** anahtarları
  (`tip|şiddet`) `cleared` olunca ya da güvenlik süresi dolunca biter ve
  cihaz geri alınır. Yeni bir `raised` süreyi uzatır.
- Neden `mode: restart` değil: uygulama `warning → critical` geçişini
  `raised(critical)` + `cleared(warning)` olarak yollar. Basit bir
  "cleared gelince geri al" kuralı cihazı fırtına sürerken açardı. Oturum
  anahtarları takip ettiği için açmaz (test: `test_escalation_does_not_restore_early`).
- **HA yeniden başlarsa:** son oturum güvenlik süresi içindeyse kalan süre
  beklenir (ya da kalkanın herhangi bir `cleared`'ı gelince) ve geri alınır.
  *Prizi kapat* / *Kapıyı kapat* ayrıca cihazın durumuna bakar: HA, süre
  dolarken kapalıysa (ör. fırtınada elektrik kesintisi) açılışta 24 saate
  kadar geri alır; cihaz zaten normal durumdaysa dokunmaz. Genel *Kalkan
  aksiyonları* şablonu cihazı göremediği için bu son durumu kapsamaz.
- Güvenlik süresi **0** yapılabilir ama önerilmez: kaçırılan tek bir
  `cleared` cihazı süresiz bırakır.

---

### Yol B — Entegrasyon (HACS)

1. HACS → Entegrasyonlar → ⋮ → **Özel depolar** →
   `https://github.com/yasinozen35/stormguard-homeassistant`, kategori
   **Integration** → **StormGuard**'ı indirin → HA'yı yeniden başlatın.
2. Ayarlar → Cihazlar ve Hizmetler → **Entegrasyon ekle** → **StormGuard**.
3. **"Ev ağı dışından gelen olayları kabul et"**: telefon evden uzaktayken de
   yayın yapacaksa açın (Nabu Casa ya da https dış adres gerekir). Kapalıyken
   dışarıdan gelen istekler HA tarafından **sessizce** düşürülür.
4. Son adımda **eşleştirme bağlantısı** gösterilir
   (`stormguardweather://home-assistant?url=…&id=…[&remote=…]`). Bağlantıyı
   StormGuard'ın yüklü olduğu telefonda açın → uygulama sunucuyu gösterip onay
   ister. Bağlantı açılmazsa aynı sayfadaki adres ve kimliği elle girin.
   Bağlantıyı sonradan entegrasyonun **Seçenekler** ekranında yeniden
   görebilirsiniz.
5. Uygulamada **Test olayı gönder** → *Son olay* sensörü güncellenir.

**Varlıklar** (tek "StormGuard" cihazı):

| Varlık | Anlamı |
|---|---|
| `binary_sensor.stormguard_electronics_shield` (ve `car`, `plants`, `clothes`) | `on` = o kalkan için **herhangi bir** risk aktif (`device_class: safety`). Öznitelikler: `active_alerts` [`type`, `severity`, `headline`, `since`, `expires_at`, `occurred_at`], `last_change`, `last_change_reason` (`raised`/`cleared`/`timeout`) |
| `sensor.stormguard_last_event` | Son kabul edilen olayın zamanı; `last_state` (`raised`/`cleared`/`test`), `profile`, `type`, `severity`, `headline` |

**Olaylar:** her kabul edilen olayda `stormguard_event` (doğrulanmış yük +
`entry_id`, `test` dahil); güvenlik süresi bir anahtarı temizlediğinde
`stormguard_expired` (`profile`, `type`, `severity`, `since`, `reason: timeout`).

**Seçenekler:** güvenlik süresi (10–720 dk, varsayılan 120) ve uzaktan erişim.
Süre **anahtar başınadır** ve her yeni `raised` ile yeniden başlar.

**Yeniden başlatma:** kalkanların durumu ve kalan süreler geri yüklenir. HA
kapalıyken süresi dolan bir anahtar, HA tamamen açıldıktan **sonra**
temizlenir — böylece `on → off` geçişini dinleyen otomasyonlarınız cihazı
geri alır.

Örnek: yıldırımda modemi kapat, risk bitince (ya da süre dolunca) aç.

```yaml
# stormguard-example: integration-modem
alias: "StormGuard — modem"
mode: queued
triggers:
  - trigger: state
    entity_id: binary_sensor.stormguard_electronics_shield
    from: "off"
    to: "on"
    id: risk
  - trigger: state
    entity_id: binary_sensor.stormguard_electronics_shield
    from: "on"
    to: "off"
    id: safe
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: risk
        sequence:
          - action: switch.turn_off
            target:
              entity_id: switch.modem
      - conditions:
          - condition: trigger
            id: safe
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.modem
```

Örnek: entegrasyonla klimalar — yalnızca açık olanları kapat, risk bitince
(ya da süre dolunca) **hâlâ kapalı** olanları eski ayarlarıyla aç. Sahneler HA
yeniden başlarsa silindiği için mod ayrıca bir Metin yardımcısında
(`input_text.stormguard_klima`, en fazla uzunluk 255) tutulur:

```yaml
# stormguard-example: integration-climate
alias: "StormGuard — klimalar"
mode: queued
triggers:
  - trigger: state
    entity_id: binary_sensor.stormguard_electronics_shield
    from: "off"
    to: "on"
    id: risk
  - trigger: state
    entity_id: binary_sensor.stormguard_electronics_shield
    from: "on"
    to: "off"
    id: safe
variables:
  acs:
    - climate.salon
    - climate.yatak_odasi
    - climate.cocuk_odasi
  memory: input_text.stormguard_klima
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: risk
        sequence:
          - variables:
              running: >-
                {{ acs | reject('is_state', ['off', 'unavailable', 'unknown']) | list }}
          - repeat:
              for_each: "{{ running }}"
              sequence:
                - action: scene.create
                  data:
                    scene_id: "stormguard_{{ repeat.item.split('.')[1] }}"
                    snapshot_entities:
                      - "{{ repeat.item }}"
          - action: input_text.set_value
            target:
              entity_id: "{{ memory }}"
            data:
              value: >-
                {% for e in running %}{{ e }}={{ states(e) }}{{ ',' if not loop.last }}{% endfor %}
          - repeat:
              for_each: "{{ running }}"
              sequence:
                - action: climate.set_hvac_mode
                  target:
                    entity_id: "{{ repeat.item }}"
                  data:
                    hvac_mode: "off"
                  continue_on_error: true
      - conditions:
          - condition: trigger
            id: safe
        sequence:
          - repeat:
              for_each: "{{ states(memory).split(',') | select('search', '=') | list }}"
              sequence:
                - variables:
                    ac: "{{ repeat.item.split('=')[0] }}"
                    mode: "{{ repeat.item.split('=')[1] }}"
                    snap: "scene.stormguard_{{ repeat.item.split('=')[0].split('.')[1] }}"
                - if:
                    - "{{ ac in acs and is_state(ac, 'off') }}"
                  then:
                    - if:
                        - "{{ state_attr(snap, 'entity_id') is not none }}"
                      then:
                        - action: scene.turn_on
                          target:
                            entity_id: "{{ snap }}"
                      else:
                        - action: climate.set_hvac_mode
                          target:
                            entity_id: "{{ ac }}"
                          data:
                            hvac_mode: "{{ mode }}"
          - action: input_text.set_value
            target:
              entity_id: "{{ memory }}"
            data:
              value: ""
```

Test olayına bildirim:

```yaml
# stormguard-example: integration-test-notification
alias: "StormGuard — test olayı geldi"
triggers:
  - trigger: event
    event_type: stormguard_event
    event_data:
      state: test
actions:
  - action: persistent_notification.create
    data:
      title: StormGuard
      message: "Test olayı ulaştı: {{ trigger.event.data.headline }}"
```

---

### Olay biçimi (sözleşme)

`POST /api/webhook/<kimlik>`, `Content-Type: application/json`, **düz** nesne
(HA'da `trigger.json.state` — `trigger.json.data.state` **değil**):

```json
{
  "source": "stormguard",
  "version": 1,
  "state": "raised",
  "profile": "electronics",
  "type": "thunderstorm",
  "severity": "critical",
  "headline": "Yıldırım riski",
  "occurredAt": "2026-10-17T10:03:00.000Z"
}
```

| Alan | Değerler | Not |
|---|---|---|
| `source` | `"stormguard"` | Zorunlu |
| `version` | tam sayı ≥ 1 | Daha yeni sürümler kabul edilir |
| `state` | `raised` · `cleared` · `test` | Bilinmeyen değer **yok sayılır** (hata değil) |
| `profile` | `electronics` · `car` · `plants` · `clothes` | `test`'te yok/`null` |
| `type` | `rain` · `thunderstorm` · `wind` · `hail` · `frost` | `test`'te yok/`null` |
| `severity` | `critical` · `warning` | `test`'te yok/`null` |
| `headline` | metin veya `null`, ≤ 500 karakter | Yalnızca `raised`/`test`'te anlamlı |
| `occurredAt` | ISO-8601 UTC | Zorunlu |

- Uygulama `raised`'i anahtar (`profile|type|severity`) başına **bir kez**
  yollar, periyodik tekrar yoktur; anahtar bitince bir kez `cleared` yollar.
- Bir kalkanın aynı anda birden çok anahtarı olabilir.
- Bilinmeyen ek alanlar yok sayılır.
- Entegrasyon geçersiz yüke **HTTP 400** döner ve hiçbir durumu değiştirmez;
  şablonlar geçersiz yükü sessizce yok sayar (HA webhook'u her zaman 200 döner).

### Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| Test olayı "gönderildi" ama hiçbir şey olmuyor | HA bilinmeyen kimliklere ve **ev ağı dışından gelen yerel-yalnız** isteklere de 200 döner. Kimliği ve "yalnızca ev ağı" ayarını kontrol edin. HA günlüğünde `Received remote request for local webhook` görüyorsanız uzaktan erişimi açın. |
| Şablon otomasyonu hiç tetiklenmiyor, günlükte `Error setting up trigger … Handler is already defined!` | Aynı kimlik StormGuard entegrasyonunda da kayıtlı. Bir kimlik için ya şablon ya entegrasyon. |
| Entegrasyon kurulumu "webhook kimliği kullanılıyor" hatası veriyor | Aynı sebep, ters yönden. |
| Eşleştirme bağlantısında "yerel adres yok" / "şifresiz" uyarısı | Ayarlar → Sistem → Ağ'da yerel adresi `http://192.168.x.x:8123` gibi bir ev ağı adresi (ya da https) yapın. Uygulama internetteki bir adrese düz `http` ile sır göndermez. |
| Cihaz fırtına bitmeden açıldı | Güvenlik süresi fırtınadan kısa. Uygulama `raised`'i tekrarlamaz; süreyi uzatın. |
| Cihaz uzun süre kapalı kaldı | `cleared` kaçtı (telefon uyuyordu); güvenlik süresi dolunca açılır. Süreyi kısaltabilirsiniz. |
| `local_only` ayarı etkisiz | Aynı kimliği paylaşan otomasyonlarda farklı değerler var; HA ilk yükleneni kullanır. |
| Fırtına sırasında otomasyonu düzenledim, cihaz geri açılmadı | Otomasyonu kaydetmek/yeniden yüklemek çalışan oturumu **iptal eder**; güvenlik süresi de onunla gider (`ha_start` yalnızca HA yeniden başlarken çalışır). Fırtına sırasında StormGuard otomasyonlarını düzenlemeyin; düzenlediyseniz cihazı elle geri açın. Dört şablon için de geçerli. |

### Geliştirme

```bash
./scripts/test.sh            # venv (uv) + ruff + pytest + hassfest
HASSFEST=0 ./scripts/test.sh # hassfest olmadan
```

---

## English

### What is this?

StormGuard is a weather-warning app. For each "shield" you enable
(electronics/modem, car, plants, laundry) it **publishes events** to Home
Assistant: `raised` (risk started), `cleared` (risk ended) and `test` (the
app's *Send test event* button — never changes a device). The app sends **no
commands** and knows **no entity ids**; the blueprints here or your own
automations decide what devices do.

**Why:** a sleeping phone cannot reliably make network requests. If the app
sent "turn the modem back on", one missed request would leave the modem off.
So every automation here restores the device on `cleared` **or** after a
safety timeout, whichever comes first. Worst case: "device was never
switched" — never "device stuck".

### Two ways

- **A. Blueprints** (no install, Home Assistant ≥ 2025.4): `switch_guard`
  (turn switches off, turn back on only those it turned off), `cover_guard`
  (close covers, optionally reopen), `climate_guard` (turn running air
  conditioners off, restore their previous settings), `shield_actions` (your
  own actions).
  Import via *Settings → Automations & Scenes → Blueprints → Import* with the
  file's GitHub URL.
- **B. Integration** (HACS custom repository
  `https://github.com/yasinozen35/stormguard-homeassistant`, category
  *Integration*): generates the webhook id, shows a **pairing link**
  (`stormguardweather://home-assistant?url=…&id=…[&remote=…]`) and provides 4
  shield `binary_sensor`s, a *Last event* sensor and the `stormguard_event` /
  `stormguard_expired` bus events. State and timers survive restarts; keys
  that expired while HA was down are cleared right **after** startup so
  automations see the `on → off` transition.

### One webhook id

The app publishes to **one** webhook id. That works for both paths:

- **A:** Home Assistant lets **several automations share one webhook id**
  (since 2022.9: `webhook/trigger.py` keeps a *list* of triggers per id and
  forwards every request to all of them). Create one automation per shield
  from the blueprints and enter the **same id** in each; each reacts only to
  its own shield. Verified in a real hass in
  `test_two_blueprints_share_one_webhook_id`. Use the same *local network
  only* value everywhere — HA uses the first registered trigger's setting.
- **B:** the integration owns the id and fans the event out to the shield
  sensors.
- **Not both with the same id:** HA binds an id either to automation triggers
  or to one integration. The integration refuses to start (clear error)
  instead of stealing the id.

### How the blueprints decide

Only `source: stormguard`, the selected shield, `raised`/`cleared` and at
least the minimum severity count; `test`, other shields and unknown states do
nothing. The first `raised` starts a **session** (`mode: single`) that keeps
listening on the same id until **all** of the shield's `type|severity` keys
are cleared or the safety timeout passes (a new `raised` extends it). This is
why it is not `mode: restart`: the app sends a warning→critical escalation as
`raised(critical)` + `cleared(warning)`, and "restore on any cleared" would
reopen during the storm. After a restart, the session resumes for the
remaining time; `switch_guard`/`cover_guard` also check device state and, if
HA was down when the timeout passed, restore on boot (within 24 h).
`shield_actions` cannot see devices and does not cover that last case.

### Air conditioners (climate_guard)

Turns the ACs that are **on** off during a lightning risk and back on with
their **previous settings** (e.g. Daikin Onecta and Midea `climate` entities).

- Off: only running ACs (never ones that are off/`unavailable`/`unknown`).
  Each gets a `scene.create` snapshot first, then `climate.set_hvac_mode: off`
  — not `climate.turn_off`, which HA only allows on entities with the
  `TURN_OFF` feature (`climate/services.py`) and errors on others.
- Restore: only ACs that are **still off** (one you turned on meanwhile is
  left alone), via `scene.turn_on` (HA's `climate/reproduce_state.py`
  replays mode, temperature, preset, swing, fan, humidity); without the scene,
  the recorded mode → temperature → fan. Never a bare `climate.turn_on`: for
  entities that do not implement it, HA picks the first of `heat_cool`,
  `heat`, `cool` (`ClimateEntity.async_turn_on`, "Fake turn on") — heat in
  summer.
- **Memory (recommended):** scenes do not survive a restart. Create a *Text*
  helper (max length **255**, no pattern — the UI default is 100) and pick it
  as *Memory*. The blueprint stores `d=<deadline>;climate.x=mode/temp/fan;…`
  and clears it after restoring; when it does not fit, fan then temperature
  are dropped, then only the ACs that fit are kept — the limit is never
  exceeded (HA silently rejects a too-long value). After a restart it resumes
  the remaining time, restores on boot if the deadline passed while HA was
  down (up to 24 h), and discards older records. **Without memory a restart
  does nothing** — it cannot know which ACs it turned off.
  **Easiest:** copy [`packages/stormguard.yaml`](packages/stormguard.yaml) to
  `config/packages/` (enable `homeassistant: packages: !include_dir_named
  packages` once), restart, and pick `input_text.stormguard_klima_hafiza`
  (max 255). It has no `initial` on purpose — that would wipe the memory on
  every restart.
- **Daikin Onecta** is cloud based with a daily request limit (about 200
  requests/day); one storm costs ~1 request per AC to turn off and 2–5 to
  restore. **Midea** is local: give the AC a static IP (DHCP reservation).
- Needs the `scene` integration (part of `default_config`).
- The integration-path equivalent (automation on
  `binary_sensor.stormguard_electronics_shield`) is the `integration-climate`
  example in the Turkish section.

### Payload contract

`POST /api/webhook/<id>`, `Content-Type: application/json`, a **flat**
object (in HA: `trigger.json.state`). See the table in the Turkish section:
`source`, `version` (≥ 1, newer accepted), `state` (`raised`/`cleared`/`test`,
unknown values ignored), `profile`, `type`, `severity` (absent/`null` for
`test`), `headline` (≤ 500 chars), `occurredAt` (ISO-8601). `raised` is sent
once per `profile|type|severity` key (no periodic resend), `cleared` once when
it ends; a shield can have several keys at once; unknown fields are ignored.
The integration answers invalid payloads with HTTP 400 and changes nothing.

### Troubleshooting

- *Sent but nothing happens:* HA answers 200 even for unknown ids and for
  remote requests to a local-only webhook. Check the id and the local-only
  setting (`Received remote request for local webhook` in the log).
- *Blueprint automation never fires (`Handler is already defined!` in the log)
  / integration says the id is in use:* the same id is used by both paths —
  pick one.
- *Pairing step warns about the local URL:* set a home-network
  (`http://192.168.x.x:8123`) or https URL under *Settings → System →
  Network*; the app never sends the secret over plain http to an internet
  host.
- *Device restored before the storm ended:* the safety timeout is shorter
  than the storm; the app does not resend `raised`.
- *Edited the automation during a storm and the device never came back:*
  saving/reloading an automation **cancels** its running session, safety
  timeout included (`ha_start` only fires when HA itself restarts). Don't edit
  StormGuard automations during a storm; if you did, restore the device by
  hand. Applies to all four blueprints.

### Development

```bash
./scripts/test.sh            # uv venv + ruff + pytest + hassfest
HASSFEST=0 ./scripts/test.sh # skip hassfest
```
