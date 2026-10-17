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
  (close covers, optionally reopen), `shield_actions` (your own actions).
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

### Development

```bash
./scripts/test.sh            # uv venv + ruff + pytest + hassfest
HASSFEST=0 ./scripts/test.sh # skip hassfest
```
