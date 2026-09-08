// MEB AI Asistan — kasa hizalama (mm)
// Orijin: kart sol-alt, Type-C kenarı = Y0, ekran yüzü = +Z
// Kart: 50 x 72 x 1.6   M2 NPTH Ø2.2

$fn = 48;

pcb_w = 50;
pcb_h = 72;
pcb_t = 1.6;

holes = [[4,10],[46,10],[4,50],[46,50]];
hole_d = 2.2;

// ESP32-S3-WROOM-1  (Top / ekran yüzü)
esp_w = 18;
esp_d = 25.5;
esp_t = 3.1;
esp_cx = 25;
esp_cy = 54;

// USB-C gövde (alt orta, karttan 1 mm taşar)
usb_w = 9.2;
usb_d = 7.5;
usb_t = 3.4;
usb_overhang = 1.0;

// J2 FPC 14P — ekran tarafı, sol
j2_w = 8;
j2_d = 12;
j2_t = 1.5;
j2_cx = 8;
j2_cy = 44;

// MK1 / MK2 (ekran yüzü, sağ alt)
mk_w = 3.5;
mk_d = 2.7;
mk_t = 1.1;

module board() {
    difference() {
        translate([0, 0, 0]) cube([pcb_w, pcb_h, pcb_t]);
        for (p = holes)
            translate([p[0], p[1], -1])
                cylinder(h = pcb_t + 2, d = hole_d);
    }
}

module esp32() {
    translate([esp_cx - esp_w/2, esp_cy - esp_d/2, pcb_t])
        cube([esp_w, esp_d, esp_t]);
}

module usbc() {
    translate([25 - usb_w/2, -usb_overhang, pcb_t])
        cube([usb_w, usb_d, usb_t]);
}

module j2() {
    translate([j2_cx - j2_w/2, j2_cy - j2_d/2, pcb_t])
        cube([j2_w, j2_d, j2_t]);
}

module mic(cx, cy) {
    translate([cx - mk_w/2, cy - mk_d/2, pcb_t])
        cube([mk_w, mk_d, mk_t]);
}

board();
esp32();
usbc();
j2();
mic(42, 16); // MK1
mic(36, 16); // MK2
