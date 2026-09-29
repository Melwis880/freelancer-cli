# DECISIONS - flx

Her satır: karar - neden. Bir karar sessizce değiştirilmez; değişmesi gerekirse önce Meriç'e sorulur.

## Mimari
- Python, sadece standart kütüphane - tedarik zinciri riski yok, kurulum kolay.
- Veri kaynağı resmi REST API (`https://www.freelancer.com/api/projects/0.1/...`), `Freelancer-OAuth-V1` başlığı - resmi SDK eski ve bakımı belirsiz.
- CLI sadece veri getirir; eleme ve puanlama teklif ajanının işi - bir araç, bir iş.
- Çekirdek (`client`, `models`) komut katmanından ayrı - ileride bir MCP katmanı aynı çekirdeği kullanabilsin.
- JSON çıktısı `schema_version` taşır - şema değişince teklif ajanı bozulmasın.
- `auth` modülünde `flx login` (OAuth) için `NotImplementedError` yer tutucusu - token panelden alınamazsa doldurulacak; o zamana kadar hiçbir şey çalışıyormuş gibi davranmaz.
- Alt komutlar standart `argparse` ile - bağımlılık yok.

## Güvenlik
- Sadece GET; başka her istek türü kod seviyesinde hata verir - teklif veya mesaj gönderimi fiziksel olarak imkânsız.
- Token `FREELANCER_TOKEN` ortam değişkeninden, yoksa projenin `.env.local` dosyasından okunur (Faz 4'te başkaları için `~/.config/flx/` yedeği eklenecek); ekrana, hata mesajına ve trace'e asla yazılmaz.
- Diske erişim: sadece `.env.local` ve `keywords.txt` okunur; sadece `traces/` ve `state/seen.json` (sadece görülen ilan ID'leri, `--only-new` için) yazılır. İkisi de git'e girmez.
- Girdi: arama metni URL'e güvenli kodlanır; ilan ID'si sadece sayı kabul edilir, değilse istek atılmaz.
- `scan` kelimeler arasında 1 sn bekler - API'yi yormamak, 429 riskini düşürmek.
- 429 (hız limiti): kademeli bekleme ile en fazla 3 tekrar (1, 2, 4 sn; `Retry-After` varsa o, en fazla 10 sn); sonra anlaşılır hata - Meriç'in tercihi, 2026-09-29.

## Trace
- Her çalıştırma `traces/YYYY-MM-DD.jsonl` dosyasına yazılır, her zaman açık - sorun anında geçmiş hazır olsun.
- Her satır: `run_id`, `seq`, zaman, komut, adım, uç nokta, parametreler, durum kodu, süre (ms), sonuç sayısı, hata - aynı `run_id` tek çalıştırmanın tüm adımlarını bağlar.
- Token hiçbir zaman yazılmaz; ilan açıklamaları kısaltılır. `traces/` git'e girmez.
- `--debug` bayrağı trace satırlarını ayrıca stderr'e basar (token maskeli) - canlı izleme için.

## Kalite
- Her gönderimde GitHub Actions ile tüm testler çalışır - regresyonlar erken yakalansın.
