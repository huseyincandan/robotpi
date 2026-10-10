# Yeni teker mesafe kalibrasyonu — doğrulama sürüyor

Motorlar kapalı, kullanıcı tarafından işaretlenmiş 1 m üzerinde elle ileri/geri.

| Yön | Sol tik büyüklüğü | Sağ tik büyüklüğü | Ortalama tik/m |
|---|---:|---:|---:|
| İleri | 13057 | 12000 | 12528,5 |
| Geri | 13208 | 12950 | 13079,0 |

İki ortalama arasında %4,3 fark var. Sol teker ileri/geri farkı yaklaşık
%1,15; sağ teker yaklaşık %7,62 (iki değerin ortalamasına göre).
Eski 21786 tik/m değeri iki ölçümle de uyuşmuyor. Elle hareket sırasında
fren direnci/kayma veya hizalama hatası ayrı ölçülmedi. Sayaçlar okuma
sırasında sabit, reset bulgusu yok. Config henüz değiştirilmedi.
Üçüncü ileri 1 m ölçümünün başlangıcı kaydedildi.

Üçüncü geçiş (ileri 1 m): sol +13091, sağ +11132; ortalama 12111,5 tik/m.
Sol üç geçişte 13057–13208 (%1,15 aralık/ortalama), sağ 11132–12950
(%15,11 aralık/ortalama). İki ileri geçişte sol yalnız 34 tik farklı,
sağ 868 tik farklı. Üçüncü geçişte sağ/sol farkı ortalamaya göre %16,17.
Bu dağılım sabit bir sağ/sol ölçek düzeltmesini desteklemiyor. Sayaç okuma
geçerliliği fiziksel ölçümün kaymasız olduğunu kanıtlamaz. Mevcut STOP
TB6612 kısa fren uygular; elle itmede teker kayması olasılığı var. Kayma,
mekanik bağlantı veya dinamik enkoder sayım kaybı henüz ayrıştırılmadı.
Bu nedenle ortak tik/metre ayarı değiştirilmedi. Dönüş/Nav2 doğrulaması
öncesinde sağ tekerin gerçek yuvarlanması gözlenmeli; aynı elle itme
prosedürünü gözlem olmadan tekrar etmek çözüm sayılmıyor.
