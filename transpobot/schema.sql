-- ============================================================
--  TranspoBot — Base de données MySQL ENRICHIE
--  Projet GLSi L3 — ESP/UCAD
--  Données de test réalistes — Transport urbain Dakar/Sénégal
-- ============================================================

CREATE DATABASE IF NOT EXISTS transpobot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE transpobot;

-- ============================================================
--  STRUCTURE DES TABLES
-- ============================================================

DROP TABLE IF EXISTS incidents;
DROP TABLE IF EXISTS trajets;
DROP TABLE IF EXISTS tarifs;
DROP TABLE IF EXISTS lignes;
DROP TABLE IF EXISTS chauffeurs;
DROP TABLE IF EXISTS vehicules;

-- Véhicules
CREATE TABLE vehicules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    immatriculation VARCHAR(20) NOT NULL UNIQUE,
    type ENUM('bus','minibus','taxi') NOT NULL,
    capacite INT NOT NULL,
    statut ENUM('actif','maintenance','hors_service') DEFAULT 'actif',
    kilometrage INT DEFAULT 0,
    date_acquisition DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chauffeurs
CREATE TABLE chauffeurs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nom VARCHAR(100) NOT NULL,
    prenom VARCHAR(100) NOT NULL,
    telephone VARCHAR(20),
    numero_permis VARCHAR(30) UNIQUE NOT NULL,
    categorie_permis VARCHAR(5),
    disponibilite BOOLEAN DEFAULT TRUE,
    vehicule_id INT,
    date_embauche DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(id)
);

-- Lignes
CREATE TABLE lignes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(10) NOT NULL UNIQUE,
    nom VARCHAR(100),
    origine VARCHAR(100) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    distance_km DECIMAL(6,2),
    duree_minutes INT
);

-- Tarifs
CREATE TABLE tarifs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ligne_id INT NOT NULL,
    type_client ENUM('normal','etudiant','senior') DEFAULT 'normal',
    prix DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (ligne_id) REFERENCES lignes(id)
);

-- Trajets
CREATE TABLE trajets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ligne_id INT NOT NULL,
    chauffeur_id INT NOT NULL,
    vehicule_id INT NOT NULL,
    date_heure_depart DATETIME NOT NULL,
    date_heure_arrivee DATETIME,
    statut ENUM('planifie','en_cours','termine','annule') DEFAULT 'planifie',
    nb_passagers INT DEFAULT 0,
    recette DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ligne_id) REFERENCES lignes(id),
    FOREIGN KEY (chauffeur_id) REFERENCES chauffeurs(id),
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(id)
);

-- Incidents
CREATE TABLE incidents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trajet_id INT NOT NULL,
    type ENUM('panne','accident','retard','autre') NOT NULL,
    description TEXT,
    gravite ENUM('faible','moyen','grave') DEFAULT 'faible',
    date_incident DATETIME NOT NULL,
    resolu BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trajet_id) REFERENCES trajets(id)
);

-- ============================================================
--  DONNÉES DE TEST ENRICHIES
-- ============================================================

-- ── 10 Véhicules ─────────────────────────────────────────────
INSERT INTO vehicules (immatriculation, type, capacite, statut, kilometrage, date_acquisition) VALUES
('DK-1234-AB', 'bus',     60, 'actif',        45000,  '2021-03-15'),
('DK-5678-CD', 'minibus', 25, 'actif',        32000,  '2022-06-01'),
('DK-9012-EF', 'bus',     60, 'maintenance',  78000,  '2019-11-20'),
('DK-3456-GH', 'taxi',     5, 'actif',       120000,  '2020-01-10'),
('DK-7890-IJ', 'minibus', 25, 'actif',        15000,  '2023-09-05'),
('DK-2345-KL', 'bus',     60, 'actif',        52000,  '2020-07-22'),
('DK-6789-MN', 'taxi',     5, 'hors_service', 195000, '2017-04-18'),
('DK-0123-OP', 'minibus', 30, 'actif',        28000,  '2022-11-30'),
('DK-4567-QR', 'bus',     55, 'actif',        61000,  '2021-08-14'),
('DK-8901-ST', 'taxi',     5, 'maintenance',  88000,  '2019-02-05');

-- ── 10 Chauffeurs ─────────────────────────────────────────────
INSERT INTO chauffeurs (nom, prenom, telephone, numero_permis, categorie_permis, vehicule_id, date_embauche) VALUES
('DIOP',    'Mamadou',   '+221771234567', 'P-2019-001', 'D', 1,    '2019-04-01'),
('FALL',    'Ibrahima',  '+221772345678', 'P-2020-002', 'D', 2,    '2020-07-15'),
('NDIAYE',  'Fatou',     '+221773456789', 'P-2021-003', 'B', 4,    '2021-02-01'),
('SECK',    'Ousmane',   '+221774567890', 'P-2022-004', 'D', 5,    '2022-10-20'),
('BA',      'Aminata',   '+221775678901', 'P-2023-005', 'D', NULL, '2023-01-10'),
('GUEYE',   'Moussa',    '+221776789012', 'P-2018-006', 'D', 6,    '2018-06-01'),
('TOURE',   'Aissatou',  '+221777890123', 'P-2020-007', 'B', 8,    '2020-03-15'),
('SARR',    'Cheikh',    '+221778901234', 'P-2021-008', 'D', 9,    '2021-09-01'),
('MBAYE',   'Rokhaya',   '+221779012345', 'P-2022-009', 'B', NULL, '2022-05-10'),
('DIOUF',   'Pape',      '+221770123456', 'P-2017-010', 'D', NULL, '2017-11-20');

-- ── 6 Lignes ──────────────────────────────────────────────────
INSERT INTO lignes (code, nom, origine, destination, distance_km, duree_minutes) VALUES
('L1', 'Ligne Dakar-Thiès',       'Dakar',        'Thiès',        70.5, 90),
('L2', 'Ligne Dakar-Mbour',       'Dakar',        'Mbour',        82.0, 120),
('L3', 'Ligne Centre-Banlieue',   'Plateau',      'Pikine',       15.0, 45),
('L4', 'Ligne Aéroport',          'Centre-ville', 'AIBD',         45.0, 60),
('L5', 'Ligne Dakar-Rufisque',    'Dakar',        'Rufisque',     25.0, 40),
('L6', 'Ligne Médina-Parcelles',  'Médina',       'Parcelles',    12.0, 35);

-- ── Tarifs ────────────────────────────────────────────────────
INSERT INTO tarifs (ligne_id, type_client, prix) VALUES
(1, 'normal', 2500), (1, 'etudiant', 1500), (1, 'senior', 1800),
(2, 'normal', 3000), (2, 'etudiant', 1800), (2, 'senior', 2200),
(3, 'normal', 500),  (3, 'etudiant', 300),  (3, 'senior', 400),
(4, 'normal', 5000), (4, 'etudiant', 3000), (4, 'senior', 4000),
(5, 'normal', 800),  (5, 'etudiant', 500),  (5, 'senior', 600),
(6, 'normal', 400),  (6, 'etudiant', 250),  (6, 'senior', 300);

-- ── 25 Trajets ────────────────────────────────────────────────
INSERT INTO trajets (ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut, nb_passagers, recette) VALUES
-- Mars 2026
(1, 1, 1, '2026-03-01 06:00:00', '2026-03-01 07:30:00', 'termine', 55, 137500),
(1, 2, 2, '2026-03-01 08:00:00', '2026-03-01 09:30:00', 'termine', 20, 50000),
(2, 3, 4, '2026-03-02 07:00:00', '2026-03-02 09:00:00', 'termine', 4,  12000),
(3, 4, 5, '2026-03-05 07:30:00', '2026-03-05 08:15:00', 'termine', 22, 11000),
(1, 1, 1, '2026-03-10 06:00:00', '2026-03-10 07:30:00', 'termine', 58, 145000),
(4, 2, 2, '2026-03-12 09:00:00', '2026-03-12 10:00:00', 'termine', 18, 90000),
(5, 6, 6, '2026-03-14 06:30:00', '2026-03-14 07:10:00', 'termine', 48, 38400),
(6, 7, 8, '2026-03-15 07:00:00', '2026-03-15 07:35:00', 'termine', 25, 10000),
(2, 8, 9, '2026-03-17 08:00:00', '2026-03-17 10:00:00', 'termine', 50, 150000),
(3, 4, 5, '2026-03-18 07:30:00', '2026-03-18 08:15:00', 'termine', 28, 14000),
(1, 6, 6, '2026-03-20 06:00:00', '2026-03-20 07:30:00', 'termine', 60, 150000),
(4, 8, 9, '2026-03-21 10:00:00', '2026-03-21 11:00:00', 'termine', 22, 110000),
(5, 1, 1, '2026-03-22 06:30:00', '2026-03-22 07:10:00', 'termine', 55, 44000),
(6, 7, 8, '2026-03-23 07:00:00', '2026-03-23 07:35:00', 'termine', 30, 12000),
(2, 2, 2, '2026-03-25 08:00:00', '2026-03-25 10:00:00', 'termine', 20, 60000),
-- Avril 2026
(1, 1, 1, '2026-04-01 06:00:00', '2026-04-01 07:30:00', 'termine', 52, 130000),
(3, 4, 5, '2026-04-01 07:30:00', '2026-04-01 08:15:00', 'termine', 25, 12500),
(4, 2, 2, '2026-04-02 09:00:00', '2026-04-02 10:00:00', 'termine', 20, 100000),
(5, 6, 6, '2026-04-03 06:30:00', '2026-04-03 07:10:00', 'termine', 45, 36000),
(6, 7, 8, '2026-04-04 07:00:00', '2026-04-04 07:35:00', 'termine', 28, 11200),
(1, 8, 9, '2026-04-05 06:00:00', '2026-04-05 07:30:00', 'termine', 54, 135000),
(2, 3, 4, '2026-04-06 08:00:00', '2026-04-06 10:00:00', 'termine', 3,  9000),
(3, 9, 5, '2026-04-07 07:30:00', '2026-04-07 08:15:00', 'termine', 20, 10000),
-- Cette semaine (en cours / planifiés)
(1, 1, 1, '2026-04-08 06:00:00', NULL,                  'en_cours', 45, 112500),
(4, 2, 2, '2026-04-09 09:00:00', NULL,                  'planifie',  0, 0);

-- ── 10 Incidents ──────────────────────────────────────────────
INSERT INTO incidents (trajet_id, type, description, gravite, date_incident, resolu) VALUES
(2,  'retard',   'Embouteillage au centre-ville de Dakar',          'faible', '2026-03-01 08:45:00', TRUE),
(3,  'panne',    'Crevaison pneu avant droit',                       'moyen',  '2026-03-02 07:30:00', TRUE),
(6,  'accident', 'Accrochage léger au rond-point de l Obélisque',   'grave',  '2026-03-12 09:20:00', FALSE),
(7,  'retard',   'Travaux sur la VDN — déviation obligatoire',      'faible', '2026-03-14 06:55:00', TRUE),
(9,  'panne',    'Surchauffe moteur — arrêt technique 20 minutes',  'moyen',  '2026-03-17 08:50:00', TRUE),
(11, 'retard',   'Surcharge passagers au terminus Petersen',        'faible', '2026-03-20 06:20:00', TRUE),
(15, 'accident', 'Collision avec moto à hauteur de Mbour',          'grave',  '2026-03-25 09:10:00', FALSE),
(16, 'panne',    'Problème de freins — immobilisation du véhicule', 'grave',  '2026-04-01 07:00:00', FALSE),
(19, 'retard',   'Manifestation bloquant la route de Rufisque',     'moyen',  '2026-04-03 07:00:00', TRUE),
(21, 'autre',    'Passager malaise — attente ambulance 15 min',     'moyen',  '2026-04-05 06:40:00', TRUE);
