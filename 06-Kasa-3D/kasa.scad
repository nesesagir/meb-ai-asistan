// MEB AI Asistan — iki parca kasa (on + arka)
// Birim: mm. OpenSCAD: F6 → STL.

$fn = 28;

W = 58;
L = 90;
T = 20;
WALL = 1.4;
FRONT_T = 5.0;          // 1.4 duvar + 3.6 ekran cebi
BACK_T = T - FRONT_T;   // 10.0
LIP = 1.0;
R_CORNER = 3.0;

PCB_W = 50;
PCB_L = 72;
PCB_X = (W - PCB_W) / 2;  // 4.0
PCB_Y = WALL;             // 1.4
POST_H = 6.5;

SCR_W = 50.4;
SCR_L = 69.6;
SCR_D = 3.6;
SCR_X = PCB_X + (PCB_W - SCR_W) / 2;
SCR_Y = PCB_Y + (PCB_L - SCR_L) / 2;

WIN_W = 44.5;
WIN_L = 59.0;
WIN_X = SCR_X + (SCR_W - WIN_W) / 2;
WIN_Y = SCR_Y + (SCR_L - WIN_L) / 2;

HOLES = [[4, 10], [46, 10], [4, 50], [46, 50]];
HOLE_R = 1.1;     // M2
POST_R = 2.2;

BAT_W = 35;
BAT_L = 34;
BAT_H = 6.5;
BAT_X = PCB_X + (PCB_W - BAT_W) / 2;
BAT_Y = PCB_Y + 13;

USB_W = 9.2;
USB_H = 3.4;
USB_Z = 4.2;
USB_X = PCB_X + 25 - USB_W / 2;

module round_rect(w, l, h, r) {
    hull() {
        translate([r, r, 0]) cylinder(h=h, r=r);
        translate([w - r, r, 0]) cylinder(h=h, r=r);
        translate([r, l - r, 0]) cylinder(h=h, r=r);
        translate([w - r, l - r, 0]) cylinder(h=h, r=r);
    }
}

module on_kapak() {
    difference() {
        union() {
            round_rect(W, L, FRONT_T, R_CORNER);
            // arka yariya giren dudak
            translate([WALL - LIP, WALL - LIP, FRONT_T])
                round_rect(W - 2 * (WALL - LIP), L - 2 * (WALL - LIP), LIP, R_CORNER - 0.4);
        }
        // ekran penceresi
        translate([WIN_X, WIN_Y, -0.2])
            cube([WIN_W, WIN_L, FRONT_T + LIP + 0.4]);
        // ekran cebi (cam oturur)
        translate([SCR_X, SCR_Y, WALL])
            cube([SCR_W, SCR_L, SCR_D + LIP + 0.2]);
        // mikrofon delikleri (alt cin, ekranin alti)
        for (dx = [-6, 6])
            translate([W / 2 + dx, 5.5, -0.2])
                cylinder(h=FRONT_T + 0.4, r=0.5);
    }
}

module arka_kapak() {
    difference() {
        round_rect(W, L, BACK_T, R_CORNER);
        // ic bosluk
        translate([WALL, WALL, WALL])
            cube([W - 2 * WALL, L - 2 * WALL, BACK_T]);
        // Type-C
        translate([USB_X, -0.2, USB_Z])
            cube([USB_W, WALL + 0.4, USB_H]);
        // hoparlor izgara
        for (i = [0:4], j = [0:2])
            translate([W - 10 + i * 1.6, L - 14 + j * 1.6, -0.2])
                cylinder(h=WALL + 0.4, r=0.55);
        // anten: ust icte vida yok (delikler zaten keep-out disinda)
    }
    // M2 direkler
    for (h = HOLES) {
        translate([PCB_X + h[0], PCB_Y + h[1], WALL])
            difference() {
                cylinder(h=POST_H, r=POST_R);
                translate([0, 0, -0.1]) cylinder(h=POST_H + 0.2, r=HOLE_R);
            }
    }
    // batarya cebi duvarlari (ESP32 altinda degil)
    translate([BAT_X - 0.8, BAT_Y - 0.8, WALL])
        difference() {
            cube([BAT_W + 1.6, BAT_L + 1.6, BAT_H]);
            translate([0.8, 0.8, 0.2]) cube([BAT_W, BAT_L, BAT_H]);
        }
}

// Onizleme: yan yana
on_kapak();
translate([W + 8, 0, 0]) arka_kapak();
