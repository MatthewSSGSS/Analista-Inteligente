"""Reconocer lugares de Colombia escritos dentro de un texto cualquiera.

Existe por un caso muy concreto y muy frecuente en los archivos reales: la
ciudad no viene en su propia columna, viene enterrada dentro del nombre del
punto de venta —"MC MULTICELL SAS CIENEGA MAGDALENA"—. Para la app eso era
texto sin significado, así que el mapa quedaba vacío aunque el archivo
estuviera lleno de ubicaciones que cualquier persona reconoce de un vistazo.

Aquí hay dos cosas: un directorio de municipios y departamentos de Colombia
con sus coordenadas, y un lector que encuentra esos nombres dentro de una
frase. Todo es local: estos casos se resuelven sin conexión y sin servicio de
geocodificación, que es justamente lo que fallaba antes.

El lector tolera errores de escritura ("CIENEGA" por "Ciénaga"), porque los
nombres de punto los escribe una persona a mano y casi nunca están limpios.
Cuando ciudad y departamento aparecen en el mismo texto, el departamento
sirve para desempatar los nombres repetidos (Villanueva existe en La Guajira,
en Casanare y en Bolívar).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

import pandas as pd

# Departamentos: coordenadas de su capital, que es donde tiene sentido dibujar
# el punto cuando el dato solo llega a nivel de departamento.
DEPARTAMENTOS: list[tuple[str, float, float]] = [
    ("Amazonas", -4.2150, -69.9406), ("Antioquia", 6.2442, -75.5812),
    ("Arauca", 7.0903, -70.7617), ("Atlántico", 10.9685, -74.7813),
    ("Bogotá D.C.", 4.7110, -74.0721), ("Bolívar", 10.3910, -75.4794),
    ("Boyacá", 5.5353, -73.3678), ("Caldas", 5.0703, -75.5138),
    ("Caquetá", 1.6144, -75.6062), ("Casanare", 5.3378, -72.3959),
    ("Cauca", 2.4448, -76.6147), ("Cesar", 10.4631, -73.2532),
    ("Chocó", 5.6947, -76.6611), ("Córdoba", 8.7479, -75.8814),
    ("Cundinamarca", 4.5709, -74.2973), ("Guainía", 3.8653, -67.9239),
    ("Guaviare", 2.5729, -72.6459), ("Huila", 2.9345, -75.2809),
    ("La Guajira", 11.5444, -72.9072), ("Magdalena", 11.2408, -74.1990),
    ("Meta", 4.1420, -73.6266), ("Nariño", 1.2136, -77.2811),
    ("Norte de Santander", 7.8939, -72.5078), ("Putumayo", 1.1523, -76.6526),
    ("Quindío", 4.5339, -75.6811), ("Risaralda", 4.8087, -75.6906),
    ("San Andrés y Providencia", 12.5847, -81.7006), ("Santander", 7.1193, -73.1227),
    ("Sucre", 9.3047, -75.3978), ("Tolima", 4.4389, -75.2322),
    ("Valle del Cauca", 3.4516, -76.5320), ("Vaupés", 1.2528, -70.2339),
    ("Vichada", 6.1889, -67.4861),
]

# Formas con las que la gente escribe los departamentos en la práctica.
ALIAS_DEPARTAMENTOS: dict[str, str] = {
    "bogota": "Bogotá D.C.", "bogota dc": "Bogotá D.C.", "bogota d c": "Bogotá D.C.",
    "distrito capital": "Bogotá D.C.",
    "guajira": "La Guajira", "valle": "Valle del Cauca",
    "norte santander": "Norte de Santander", "n de santander": "Norte de Santander",
    "nte de santander": "Norte de Santander",
    "san andres islas": "San Andrés y Providencia",
    "archipielago de san andres": "San Andrés y Providencia",
}

# Municipios: (nombre, departamento, lat, lon). No es el listado completo de
# los más de mil municipios del país; cubre capitales y municipios con
# presencia comercial real, que son los que aparecen en un Excel de negocio.
# El orden importa: cuando un nombre se repite entre departamentos, el primero
# de la lista es el que gana si el texto no aclara el departamento.
MUNICIPIOS: list[tuple[str, str, float, float]] = [
    # Amazonas
    ("Leticia", "Amazonas", -4.2150, -69.9406),
    ("Puerto Nariño", "Amazonas", -3.7833, -70.3667),
    # Antioquia
    ("Medellín", "Antioquia", 6.2442, -75.5812), ("Bello", "Antioquia", 6.3373, -75.5545),
    ("Itagüí", "Antioquia", 6.1719, -75.6113), ("Envigado", "Antioquia", 6.1667, -75.5833),
    ("Rionegro", "Antioquia", 6.1550, -75.3739), ("Apartadó", "Antioquia", 7.8829, -76.6256),
    ("Turbo", "Antioquia", 8.0940, -76.7280), ("Sabaneta", "Antioquia", 6.1515, -75.6166),
    ("Caldas", "Antioquia", 6.0917, -75.6361), ("Copacabana", "Antioquia", 6.3467, -75.5083),
    ("La Estrella", "Antioquia", 6.1578, -75.6433), ("Girardota", "Antioquia", 6.3781, -75.4453),
    ("Caucasia", "Antioquia", 7.9869, -75.1981), ("Chigorodó", "Antioquia", 7.6664, -76.6811),
    ("Carepa", "Antioquia", 7.7561, -76.6531), ("Necoclí", "Antioquia", 8.4258, -76.7869),
    ("Marinilla", "Antioquia", 6.1739, -75.3392), ("La Ceja", "Antioquia", 6.0294, -75.4297),
    ("Yarumal", "Antioquia", 6.9636, -75.4181), ("Santa Fe de Antioquia", "Antioquia", 6.5569, -75.8267),
    ("Puerto Berrío", "Antioquia", 6.4886, -74.4053), ("El Bagre", "Antioquia", 7.5967, -74.8092),
    ("Segovia", "Antioquia", 7.0800, -74.7000), ("Andes", "Antioquia", 5.6578, -75.8789),
    # Arauca
    ("Arauca", "Arauca", 7.0903, -70.7617), ("Saravena", "Arauca", 6.9553, -71.8747),
    ("Arauquita", "Arauca", 7.0289, -71.4278), ("Tame", "Arauca", 6.4600, -71.7400),
    # Atlántico
    ("Barranquilla", "Atlántico", 10.9685, -74.7813), ("Soledad", "Atlántico", 10.9172, -74.7669),
    ("Malambo", "Atlántico", 10.8592, -74.7739), ("Sabanalarga", "Atlántico", 10.6303, -74.9203),
    ("Puerto Colombia", "Atlántico", 10.9897, -74.9547), ("Galapa", "Atlántico", 10.8994, -74.8864),
    ("Baranoa", "Atlántico", 10.7947, -74.9161), ("Sabanagrande", "Atlántico", 10.7889, -74.7550),
    ("Santo Tomás", "Atlántico", 10.7594, -74.7550), ("Palmar de Varela", "Atlántico", 10.7397, -74.7547),
    # Bolívar
    ("Cartagena", "Bolívar", 10.3910, -75.4794), ("Magangué", "Bolívar", 9.2419, -74.7539),
    ("Turbaco", "Bolívar", 10.3364, -75.4111), ("Arjona", "Bolívar", 10.2547, -75.3439),
    ("El Carmen de Bolívar", "Bolívar", 9.7181, -75.1214), ("Mompox", "Bolívar", 9.2408, -74.4258),
    ("San Juan Nepomuceno", "Bolívar", 9.9531, -75.0836), ("María la Baja", "Bolívar", 9.9831, -75.3011),
    # Boyacá
    ("Tunja", "Boyacá", 5.5353, -73.3678), ("Duitama", "Boyacá", 5.8244, -73.0342),
    ("Sogamoso", "Boyacá", 5.7147, -72.9339), ("Chiquinquirá", "Boyacá", 5.6172, -73.8181),
    ("Paipa", "Boyacá", 5.7803, -73.1169), ("Puerto Boyacá", "Boyacá", 5.9761, -74.5892),
    ("Villa de Leyva", "Boyacá", 5.6339, -73.5253), ("Garagoa", "Boyacá", 5.0825, -73.3636),
    ("Moniquirá", "Boyacá", 5.8756, -73.5731),
    # Caldas
    ("Manizales", "Caldas", 5.0703, -75.5138), ("La Dorada", "Caldas", 5.4581, -74.6689),
    ("Chinchiná", "Caldas", 4.9828, -75.6067), ("Villamaría", "Caldas", 5.0453, -75.5119),
    ("Riosucio", "Caldas", 5.4222, -75.7031), ("Anserma", "Caldas", 5.2364, -75.7844),
    ("Salamina", "Caldas", 5.4050, -75.4869),
    # Caquetá
    ("Florencia", "Caquetá", 1.6144, -75.6062), ("San Vicente del Caguán", "Caquetá", 2.1150, -74.7708),
    ("El Doncello", "Caquetá", 1.6797, -75.2822),
    # Casanare
    ("Yopal", "Casanare", 5.3378, -72.3959), ("Aguazul", "Casanare", 5.1725, -72.5472),
    ("Tauramena", "Casanare", 5.0175, -72.7469), ("Paz de Ariporo", "Casanare", 5.8797, -71.8917),
    ("Monterrey", "Casanare", 4.8867, -72.8925),
    # Cauca
    ("Popayán", "Cauca", 2.4448, -76.6147), ("Santander de Quilichao", "Cauca", 3.0097, -76.4850),
    ("Puerto Tejada", "Cauca", 3.2350, -76.4192), ("Guapi", "Cauca", 2.5714, -77.8875),
    ("Miranda", "Cauca", 3.2494, -76.2281), ("Corinto", "Cauca", 3.1728, -76.2603),
    ("Piendamó", "Cauca", 2.6392, -76.5311),
    # Cesar
    ("Valledupar", "Cesar", 10.4631, -73.2532), ("Aguachica", "Cesar", 8.3094, -73.6144),
    ("Bosconia", "Cesar", 9.9758, -73.8894), ("Agustín Codazzi", "Cesar", 10.0369, -73.2364),
    ("La Jagua de Ibirico", "Cesar", 9.5633, -73.3339), ("Curumaní", "Cesar", 9.2000, -73.5417),
    ("El Copey", "Cesar", 10.1500, -73.9611), ("Chiriguaná", "Cesar", 9.3639, -73.6017),
    ("San Diego", "Cesar", 10.3350, -73.1817), ("Pailitas", "Cesar", 8.9564, -73.6256),
    # Chocó
    ("Quibdó", "Chocó", 5.6947, -76.6611), ("Istmina", "Chocó", 5.1594, -76.6844),
    ("Acandí", "Chocó", 8.5133, -77.2778), ("Bahía Solano", "Chocó", 6.2233, -77.4083),
    ("Condoto", "Chocó", 5.0919, -76.6467),
    # Córdoba
    ("Montería", "Córdoba", 8.7479, -75.8814), ("Lorica", "Córdoba", 9.2394, -75.8144),
    ("Cereté", "Córdoba", 8.8853, -75.7906), ("Sahagún", "Córdoba", 8.9472, -75.4458),
    ("Planeta Rica", "Córdoba", 8.4111, -75.5844), ("Montelíbano", "Córdoba", 7.9744, -75.4189),
    ("Tierralta", "Córdoba", 8.1719, -76.0597), ("Chinú", "Córdoba", 9.1058, -75.4008),
    ("San Pelayo", "Córdoba", 8.9581, -75.8347), ("Ayapel", "Córdoba", 8.3131, -75.1394),
    ("Puerto Libertador", "Córdoba", 7.8894, -75.6733), ("Moñitos", "Córdoba", 9.2444, -76.1272),
    ("San Antero", "Córdoba", 9.3736, -75.7592), ("San Bernardo del Viento", "Córdoba", 9.3547, -75.9539),
    # Bogotá y Cundinamarca
    ("Bogotá", "Bogotá D.C.", 4.7110, -74.0721), ("Soacha", "Cundinamarca", 4.5794, -74.2169),
    ("Facatativá", "Cundinamarca", 4.8144, -74.3547), ("Zipaquirá", "Cundinamarca", 5.0221, -74.0047),
    ("Chía", "Cundinamarca", 4.8611, -74.0322), ("Fusagasugá", "Cundinamarca", 4.3439, -74.3644),
    ("Girardot", "Cundinamarca", 4.3050, -74.8011), ("Mosquera", "Cundinamarca", 4.7058, -74.2306),
    ("Madrid", "Cundinamarca", 4.7325, -74.2642), ("Funza", "Cundinamarca", 4.7161, -74.2119),
    ("Cajicá", "Cundinamarca", 4.9181, -74.0281), ("Ubaté", "Cundinamarca", 5.3081, -73.8150),
    ("La Calera", "Cundinamarca", 4.7208, -73.9694), ("Sibaté", "Cundinamarca", 4.4919, -74.2597),
    ("Tocancipá", "Cundinamarca", 4.9642, -73.9139), ("Cota", "Cundinamarca", 4.8092, -74.0983),
    ("Villeta", "Cundinamarca", 5.0117, -74.4736), ("La Mesa", "Cundinamarca", 4.6322, -74.4633),
    ("Anapoima", "Cundinamarca", 4.5533, -74.5350), ("Cáqueza", "Cundinamarca", 4.4083, -73.9450),
    ("Guaduas", "Cundinamarca", 5.0722, -74.5981), ("Pacho", "Cundinamarca", 5.1306, -74.1583),
    ("Chocontá", "Cundinamarca", 5.1450, -73.6858),
    # Guainía / Guaviare
    ("Inírida", "Guainía", 3.8653, -67.9239),
    ("San José del Guaviare", "Guaviare", 2.5729, -72.6459),
    # Huila
    ("Neiva", "Huila", 2.9345, -75.2809), ("Pitalito", "Huila", 1.8517, -76.0508),
    ("Garzón", "Huila", 2.1969, -75.6278), ("La Plata", "Huila", 2.3931, -75.8917),
    ("Campoalegre", "Huila", 2.6858, -75.3247), ("Gigante", "Huila", 2.3861, -75.5461),
    ("Palermo", "Huila", 2.8894, -75.4353),
    # La Guajira
    ("Riohacha", "La Guajira", 11.5444, -72.9072), ("Maicao", "La Guajira", 11.3778, -72.2394),
    ("Uribia", "La Guajira", 11.7139, -72.2658), ("Manaure", "La Guajira", 11.7756, -72.4458),
    ("Fonseca", "La Guajira", 10.8853, -72.8481), ("San Juan del Cesar", "La Guajira", 10.7714, -73.0033),
    ("Villanueva", "La Guajira", 10.6058, -72.9767), ("Barrancas", "La Guajira", 10.9578, -72.7897),
    ("Albania", "La Guajira", 11.1611, -72.5919), ("Dibulla", "La Guajira", 11.2731, -73.3097),
    ("Hatonuevo", "La Guajira", 11.0692, -72.7658),
    # Magdalena
    ("Santa Marta", "Magdalena", 11.2408, -74.1990), ("Ciénaga", "Magdalena", 11.0072, -74.2469),
    ("Fundación", "Magdalena", 10.5219, -74.1856), ("El Banco", "Magdalena", 9.0006, -73.9744),
    ("Plato", "Magdalena", 9.7936, -74.7844), ("Aracataca", "Magdalena", 10.5919, -74.1889),
    ("Zona Bananera", "Magdalena", 10.7667, -74.1500), ("Pivijay", "Magdalena", 10.4644, -74.6144),
    ("Sitionuevo", "Magdalena", 10.7758, -74.7217), ("Santa Ana", "Magdalena", 9.3250, -74.5711),
    # Meta
    ("Villavicencio", "Meta", 4.1420, -73.6266), ("Acacías", "Meta", 3.9878, -73.7597),
    ("Granada", "Meta", 3.5464, -73.7061), ("Puerto López", "Meta", 4.0844, -72.9553),
    ("Puerto Gaitán", "Meta", 4.3125, -72.0819), ("San Martín", "Meta", 3.6975, -73.6981),
    ("Cumaral", "Meta", 4.2703, -73.4869), ("Restrepo", "Meta", 4.2597, -73.5606),
    # Nariño
    ("Pasto", "Nariño", 1.2136, -77.2811), ("Ipiales", "Nariño", 0.8281, -77.6444),
    ("Tumaco", "Nariño", 1.7986, -78.7644), ("Túquerres", "Nariño", 1.0872, -77.6181),
    ("Samaniego", "Nariño", 1.3358, -77.5953), ("Sandoná", "Nariño", 1.2872, -77.4728),
    ("La Unión", "Nariño", 1.6031, -77.1319),
    # Norte de Santander
    ("Cúcuta", "Norte de Santander", 7.8939, -72.5078), ("Ocaña", "Norte de Santander", 8.2378, -73.3561),
    ("Pamplona", "Norte de Santander", 7.3775, -72.6486), ("Villa del Rosario", "Norte de Santander", 7.8342, -72.4747),
    ("Los Patios", "Norte de Santander", 7.8342, -72.5008), ("Tibú", "Norte de Santander", 8.6394, -72.7361),
    ("Chinácota", "Norte de Santander", 7.6058, -72.6011),
    # Putumayo
    ("Mocoa", "Putumayo", 1.1523, -76.6526), ("Puerto Asís", "Putumayo", 0.5117, -76.4972),
    ("Orito", "Putumayo", 0.6642, -76.8722), ("La Hormiga", "Putumayo", 0.4364, -76.9061),
    ("Sibundoy", "Putumayo", 1.2058, -76.9203),
    # Quindío
    ("Armenia", "Quindío", 4.5339, -75.6811), ("Calarcá", "Quindío", 4.5253, -75.6428),
    ("Montenegro", "Quindío", 4.5642, -75.7500), ("Quimbaya", "Quindío", 4.6222, -75.7628),
    ("La Tebaida", "Quindío", 4.4531, -75.7864), ("Circasia", "Quindío", 4.6169, -75.6353),
    ("Filandia", "Quindío", 4.6742, -75.6575), ("Salento", "Quindío", 4.6372, -75.5706),
    # Risaralda
    ("Pereira", "Risaralda", 4.8087, -75.6906), ("Dosquebradas", "Risaralda", 4.8339, -75.6811),
    ("Santa Rosa de Cabal", "Risaralda", 4.8697, -75.6247), ("La Virginia", "Risaralda", 4.8992, -75.8828),
    ("Belén de Umbría", "Risaralda", 5.2003, -75.8683),
    # San Andrés y Providencia
    ("San Andrés", "San Andrés y Providencia", 12.5847, -81.7006),
    ("Providencia", "San Andrés y Providencia", 13.3489, -81.3742),
    # Santander
    ("Bucaramanga", "Santander", 7.1193, -73.1227), ("Floridablanca", "Santander", 7.0625, -73.0864),
    ("Girón", "Santander", 7.0736, -73.1697), ("Piedecuesta", "Santander", 6.9878, -73.0500),
    ("Barrancabermeja", "Santander", 7.0653, -73.8547), ("San Gil", "Santander", 6.5544, -73.1331),
    ("Socorro", "Santander", 6.4636, -73.2617), ("Málaga", "Santander", 6.7003, -72.7328),
    ("Vélez", "Santander", 6.0106, -73.6725), ("Sabana de Torres", "Santander", 7.3919, -73.4972),
    ("Barbosa", "Santander", 5.9314, -73.6156), ("Puerto Wilches", "Santander", 7.3494, -73.8983),
    # Sucre
    ("Sincelejo", "Sucre", 9.3047, -75.3978), ("Corozal", "Sucre", 9.3186, -75.2942),
    ("Sampués", "Sucre", 9.1839, -75.3800), ("San Marcos", "Sucre", 8.6606, -75.1289),
    ("Sincé", "Sucre", 9.2436, -75.1450), ("Tolú", "Sucre", 9.5250, -75.5833),
    ("Coveñas", "Sucre", 9.4022, -75.6800), ("Majagual", "Sucre", 8.5386, -74.6247),
    ("Los Palmitos", "Sucre", 9.3792, -75.2711), ("Morroa", "Sucre", 9.3339, -75.3061),
    ("Ovejas", "Sucre", 9.5269, -75.2286),
    # Tolima
    ("Ibagué", "Tolima", 4.4389, -75.2322), ("Espinal", "Tolima", 4.1531, -74.8850),
    ("Melgar", "Tolima", 4.2044, -74.6428), ("Honda", "Tolima", 5.2078, -74.7369),
    ("Chaparral", "Tolima", 3.7239, -75.4844), ("Líbano", "Tolima", 4.9219, -75.0625),
    ("Mariquita", "Tolima", 5.1994, -74.8933), ("Purificación", "Tolima", 3.8567, -74.9328),
    ("Flandes", "Tolima", 4.2914, -74.8161), ("Guamo", "Tolima", 4.0300, -74.9711),
    ("Fresno", "Tolima", 5.1531, -75.0364), ("Lérida", "Tolima", 4.8631, -74.9111),
    # Valle del Cauca
    ("Cali", "Valle del Cauca", 3.4516, -76.5320), ("Palmira", "Valle del Cauca", 3.5394, -76.3036),
    ("Buenaventura", "Valle del Cauca", 3.8801, -77.0313), ("Tuluá", "Valle del Cauca", 4.0847, -76.1954),
    ("Cartago", "Valle del Cauca", 4.7464, -75.9117), ("Buga", "Valle del Cauca", 3.9006, -76.2978),
    ("Jamundí", "Valle del Cauca", 3.2619, -76.5397), ("Yumbo", "Valle del Cauca", 3.5850, -76.4956),
    ("Candelaria", "Valle del Cauca", 3.4067, -76.3475), ("Florida", "Valle del Cauca", 3.3244, -76.2350),
    ("Pradera", "Valle del Cauca", 3.4206, -76.2417), ("Zarzal", "Valle del Cauca", 4.3925, -76.0714),
    ("Roldanillo", "Valle del Cauca", 4.4131, -76.1533), ("Sevilla", "Valle del Cauca", 4.2711, -75.9358),
    ("Caicedonia", "Valle del Cauca", 4.3339, -75.8306), ("El Cerrito", "Valle del Cauca", 3.6858, -76.3128),
    ("Ginebra", "Valle del Cauca", 3.7242, -76.2681), ("Guacarí", "Valle del Cauca", 3.7628, -76.3319),
    ("Dagua", "Valle del Cauca", 3.6572, -76.6883),
    # Vaupés / Vichada
    ("Mitú", "Vaupés", 1.2528, -70.2339),
    ("Puerto Carreño", "Vichada", 6.1889, -67.4861), ("La Primavera", "Vichada", 5.4906, -70.4097),
    # Homónimos. Van al final a propósito: cuando el texto no dice el
    # departamento gana el municipio más conocido, que aparece antes; cuando
    # sí lo dice, el departamento elige a cuál de los dos se refiere.
    ("Villanueva", "Casanare", 4.6108, -72.9281), ("Villanueva", "Bolívar", 10.4436, -75.2744),
    ("Villanueva", "Santander", 6.6706, -73.1747),
    ("La Unión", "Valle del Cauca", 4.5300, -76.1017), ("La Unión", "Antioquia", 5.9736, -75.3603),
    ("Granada", "Antioquia", 6.1428, -75.1839), ("Granada", "Cundinamarca", 4.5178, -74.3506),
    ("Barbosa", "Antioquia", 6.4386, -75.3317), ("Candelaria", "Atlántico", 10.4589, -74.8811),
    ("Restrepo", "Valle del Cauca", 3.8206, -76.5231), ("San Martín", "Cesar", 8.0011, -73.5100),
    ("Puerto Rico", "Caquetá", 1.9106, -75.1594), ("Puerto Rico", "Meta", 2.9394, -73.2081),
    ("Miranda", "Boyacá", 5.8206, -73.5906), ("Sevilla", "Magdalena", 10.7503, -74.1394),
    ("San Marcos", "Antioquia", 6.5486, -74.7053), ("Albania", "Santander", 5.7594, -73.9139),
    ("Santa Rosa", "Bolívar", 10.4444, -75.3689), ("Córdoba", "Bolívar", 9.5872, -74.8281),
    ("Sucre", "Sucre", 8.8106, -74.7208), ("Sucre", "Santander", 5.9186, -73.7906),
    ("Cartagena del Chairá", "Caquetá", 1.3339, -74.8419),
]

# Formas alternativas con las que se escribe un municipio en los archivos.
ALIAS_MUNICIPIOS: dict[str, str] = {
    "santafe de bogota": "Bogotá", "bogota dc": "Bogotá", "bogota d c": "Bogotá",
    "san andres isla": "San Andrés", "san andres islas": "San Andrés",
    "codazzi": "Agustín Codazzi", "santa cruz de mompox": "Mompox", "mompos": "Mompox",
    "guadalajara de buga": "Buga", "santiago de cali": "Cali",
    "san jose de cucuta": "Cúcuta", "san juan de pasto": "Pasto",
    "villa de san diego de ubate": "Ubaté", "valle de upar": "Valledupar",
}

# Palabras que abundan en los nombres comerciales y nunca son un lugar. Solo
# se usan para no malgastar la comparación aproximada en ellas.
_RUIDO = {
    "sas", "sa", "ltda", "eu", "sc", "cia", "compania", "empresa", "grupo",
    "comunicaciones", "comunicacion", "inversiones", "inversion", "distribuciones",
    "distribuidora", "comercializadora", "tecnologia", "tecnologias", "soluciones",
    "servicios", "servicio", "centro", "punto", "puntos", "tienda", "almacen",
    "sucursal", "agencia", "oficina", "sede", "local", "principal", "norte", "sur",
    "este", "oeste", "movil", "celular", "celulares", "digital", "express", "plus",
    "shop", "store", "mundo", "casa", "multiservicios", "del", "los", "las",
    "san", "santa", "nueva", "nuevo",
}

# Encabezados que sugieren que la columna describe un lugar físico. No es
# requisito, pero ayuda a elegir entre varias columnas candidatas.
_PISTAS_ENCABEZADO = (
    "punto", "pdv", "sede", "sucursal", "oficina", "agencia", "tienda", "almacen",
    "local", "establecimiento", "direccion", "ubicacion", "zona", "territorio",
    "plaza", "distribuidor", "aliado", "canal", "lugar", "site",
)


def normalizar(texto) -> str:
    """Texto comparable: sin tildes, sin signos, en minúsculas."""
    if texto is None:
        return ""
    if isinstance(texto, float) and pd.isna(texto):
        return ""
    limpio = unicodedata.normalize("NFKD", str(texto))
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    limpio = re.sub(r"[^0-9a-zA-Z]+", " ", limpio.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def _construir_indices():
    municipios: dict[str, list[tuple[str, str, float, float]]] = {}
    for nombre, depto, lat, lon in MUNICIPIOS:
        municipios.setdefault(normalizar(nombre), []).append((nombre, depto, lat, lon))
    for alias, nombre in ALIAS_MUNICIPIOS.items():
        destino = municipios.get(normalizar(nombre))
        if destino:
            municipios.setdefault(normalizar(alias), []).extend(destino)

    departamentos: dict[str, tuple[str, float, float]] = {}
    for nombre, lat, lon in DEPARTAMENTOS:
        departamentos[normalizar(nombre)] = (nombre, lat, lon)
    for alias, nombre in ALIAS_DEPARTAMENTOS.items():
        destino = departamentos.get(normalizar(nombre))
        if destino:
            departamentos[normalizar(alias)] = destino
    return municipios, departamentos


_MUNICIPIOS_IDX, _DEPARTAMENTOS_IDX = _construir_indices()
_MAX_PALABRAS = max(len(k.split()) for k in list(_MUNICIPIOS_IDX) + list(_DEPARTAMENTOS_IDX))

# Claves agrupadas por inicial: la comparación aproximada recorre solo el
# grupo que empieza igual, no el directorio completo.
_POR_INICIAL: dict[str, list[str]] = {}
for _clave in _MUNICIPIOS_IDX:
    _POR_INICIAL.setdefault(_clave[0], []).append(_clave)


def _mejor_aproximado(fragmento: str, depto: Optional[str], umbral: float = 0.85):
    """El municipio más parecido a un fragmento mal escrito, si lo hay."""
    if len(fragmento) < 5 or fragmento in _RUIDO or fragmento.isdigit():
        return None
    mejor, mejor_puntaje = None, 0.0
    for clave in _POR_INICIAL.get(fragmento[0], ()):
        if abs(len(clave) - len(fragmento)) > 3:
            continue
        parecido = SequenceMatcher(None, fragmento, clave).ratio()
        if parecido < 0.80:
            continue
        # Si el texto ya nombró el departamento, el municipio que pertenece a
        # ese departamento es el candidato correcto casi siempre: eso permite
        # aceptar una escritura un poco peor sin abrir la puerta a cualquiera.
        puntaje = parecido + (0.06 if depto and any(e[1] == depto for e in _MUNICIPIOS_IDX[clave]) else 0)
        if puntaje < umbral:
            continue
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = clave, puntaje
    return (mejor, mejor_puntaje) if mejor else None


def _elegir(candidatos, depto: Optional[str]):
    """El municipio del departamento nombrado; si no, el más conocido."""
    return next((c for c in candidatos if c[1] == depto), candidatos[0])


def buscar_lugar(texto) -> Optional[dict]:
    """Encuentra el municipio (o el departamento) nombrado dentro del texto.

    Devuelve None cuando no hay ningún lugar reconocible, que es lo correcto:
    preferimos no ubicar un punto antes que ubicarlo mal.
    """
    limpio = normalizar(texto)
    if not limpio:
        return None
    palabras = limpio.split()
    total = len(palabras)

    # Coincidencias exactas. Gana el nombre más largo ("Santa Marta" antes que
    # "Santa") y, a igual longitud, el que aparece más al final: en un nombre
    # comercial el lugar casi siempre va al cierre.
    def buscar_exacto(indice, excluir: set):
        hallado = None
        for largo in range(min(_MAX_PALABRAS, total), 0, -1):
            for inicio in range(total - largo + 1):
                if excluir.intersection(range(inicio, inicio + largo)):
                    continue
                fragmento = " ".join(palabras[inicio:inicio + largo])
                if fragmento in indice and (hallado is None or (largo == hallado[0] and inicio > hallado[1])):
                    hallado = (largo, inicio, fragmento)
        return hallado

    # El departamento se busca primero y su lugar en la frase queda reservado.
    # Sin eso, un nombre que es municipio y departamento a la vez —Córdoba,
    # Sucre— se llevaba el punto por estar más al final, y "MONTERIA CORDOBA"
    # terminaba ubicado en el departamento en vez de en Montería.
    depto = buscar_exacto(_DEPARTAMENTOS_IDX, set())
    ocupado = set(range(depto[1], depto[1] + depto[0])) if depto else set()
    depto_nombre = _DEPARTAMENTOS_IDX[depto[2]][0] if depto else None
    muni = buscar_exacto(_MUNICIPIOS_IDX, ocupado) or buscar_exacto(_MUNICIPIOS_IDX, set())

    def resultado_departamento() -> dict:
        nombre, lat, lon = _DEPARTAMENTOS_IDX[depto[2]]
        return {
            "lugar": nombre, "departamento": nombre, "lat": lat, "lon": lon,
            "nivel": "departamento", "exacto": True, "fragmento": depto[2],
        }

    def resolver(clave: str, exacto: bool) -> dict:
        elegido = _elegir(_MUNICIPIOS_IDX[clave], depto_nombre)
        if depto_nombre and elegido[1] != depto_nombre:
            # El texto nombra un departamento al que este municipio no
            # pertenece: hay un municipio homónimo que no está en el
            # directorio. Ubicamos el departamento, que sí es seguro, en vez
            # de mandar el punto a otra región del país.
            return resultado_departamento()
        return {
            "lugar": elegido[0], "departamento": elegido[1],
            "lat": elegido[2], "lon": elegido[3],
            "nivel": "municipio", "exacto": exacto, "fragmento": clave,
        }

    if muni:
        return resolver(muni[2], True)

    # Sin coincidencia exacta probamos escritura aproximada sobre fragmentos de
    # una a tres palabras. Aquí es donde "CIENEGA" encuentra a "Ciénaga".
    mejor = None
    for largo in (1, 2, 3):
        for inicio in range(total - largo + 1):
            if ocupado.intersection(range(inicio, inicio + largo)):
                continue
            hallazgo = _mejor_aproximado(" ".join(palabras[inicio:inicio + largo]), depto_nombre)
            if hallazgo and (mejor is None or hallazgo[1] > mejor[1]
                             or (hallazgo[1] == mejor[1] and inicio > mejor[2])):
                mejor = (hallazgo[0], hallazgo[1], inicio)
    if mejor:
        return resolver(mejor[0], False)

    return resultado_departamento() if depto else None


def leer_columna(valores) -> dict:
    """Resuelve una lista de textos y resume qué tan geográfica resultó ser."""
    resultados = {v: buscar_lugar(v) for v in valores}
    encontrados = {v: r for v, r in resultados.items() if r}
    municipios = sum(1 for r in encontrados.values() if r["nivel"] == "municipio")
    departamentos = len(encontrados) - municipios
    total = max(len(resultados), 1)
    return {
        "resultados": resultados,
        # El departamento vale la mitad: es una señal más débil y es también
        # la que más se parece a un apellido suelto (Córdoba, Santander).
        "cobertura": (municipios + 0.5 * departamentos) / total,
        "municipios": municipios,
        "departamentos": departamentos,
        "lugares": len({r["lugar"] for r in encontrados.values()}),
        "aproximados": sum(1 for r in encontrados.values() if not r["exacto"]),
        "total": total,
    }


def columna_con_lugares(
    df: pd.DataFrame,
    excluir: set | None = None,
    cobertura_minima: float = 0.6,
    muestra: int = 400,
) -> tuple[Optional[str], dict]:
    """La columna de texto que mejor esconde ubicaciones, si es que hay alguna.

    El umbral es deliberadamente exigente. Una columna de nombres de persona
    también tiene apellidos que coinciden con municipios (Córdoba, Pereira), y
    ubicar clientes por su apellido sería peor que no ubicarlos.
    """
    excluidas = {str(c) for c in (excluir or set())}
    mejor, mejor_puntaje, mejor_info = None, 0.0, {}
    for col in df.columns:
        nombre = str(col)
        if nombre in excluidas or nombre.startswith("_"):
            continue
        serie = df[col]
        if not (serie.dtype == object or pd.api.types.is_string_dtype(serie)):
            continue
        textos = serie.dropna().astype(str).str.strip()
        textos = textos[textos.ne("") & textos.str.lower().ne("nan")]
        if textos.empty:
            continue
        unicos = textos.drop_duplicates()
        if len(unicos) > muestra:
            unicos = unicos.head(muestra)
        info = leer_columna(list(unicos))
        if info["cobertura"] < cobertura_minima or info["lugares"] < 1:
            continue
        # Un solo lugar en toda la columna se acepta únicamente si la lectura
        # fue casi perfecta; si no, es más probable que sea una casualidad.
        if info["lugares"] < 2 and info["cobertura"] < 0.85:
            continue
        encabezado = normalizar(nombre)
        pista = any(p in encabezado for p in _PISTAS_ENCABEZADO)
        puntaje = info["cobertura"] + (0.15 if pista else 0) + min(info["lugares"], 20) / 200
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje, mejor_info = nombre, puntaje, info
    if mejor is None:
        return None, {}
    return mejor, {
        "cobertura": mejor_info["cobertura"],
        "lugares": mejor_info["lugares"],
        "municipios": mejor_info["municipios"],
        "departamentos": mejor_info["departamentos"],
        "aproximados": mejor_info["aproximados"],
        "revisados": mejor_info["total"],
    }
