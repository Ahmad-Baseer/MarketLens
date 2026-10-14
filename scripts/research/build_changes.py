"""Build index_changes.csv from hand-transcribed PSX index recomposition notices.

Every pair below was read from the notice page image / text (page 1, or the
annexure page for 189483). Names are cleaned for spacing only; obvious source
typos are fixed and listed in the report.
"""
import csv
import os

SRC = r"D:\Investments\MBF\data\raw\notices"
OUT = os.path.join(SRC, "index_changes.csv")

MCB = "Market Capitalization Based Rule"
SBR = "Sector Based Rule"
NC = "Non Compliant"
NT = "Not in top 30"  # footnote: not within top-30 ranked Shariah-compliant stocks


def R(n):
    return f"Ranks {n}"


# Each notice: (doc_id, effective_date, [entries]); entries are
#   ("P", index, in_name, in_sym, out_name, out_sym, in_reason, out_reason)  paired swap
NOTICES = []


def add(doc_id, eff, entries):
    NOTICES.append((doc_id, eff, entries))


def kse100(pairs):
    """KSE-100 table: (in, out, reason) -> reason applies to the swap (both rows)."""
    return [("P", "KSE100", i, "", o, "", r, r) for i, o, r in pairs]


def excl(index, pairs, in_reason=""):
    """Exclusion-reason table: (in, out, out_reason)."""
    return [("P", index, i, "", o, "", in_reason, r) for i, o, r in pairs]


def tick(index, pairs, reason=""):
    """Table with printed tickers: (in_sym, in, out_sym, out)."""
    return [("P", index, i, isym, o, osym, reason, reason) for isym, i, osym, o in pairs]


add("49412", "2013-12-16", excl("KMI30", [
    ("Fauji Cement", "Attock Cement", ""),
    ("Attock Petroleum Ltd", "Abbott Lab.", ""),
    ("Sui Northern Gas", "Pak Suzuki", ""),
    ("Pakgen Power Ltd", "ICI Pakistan", ""),
    ("Netsol Technologies", "Indus Motor", ""),
]))
add("66630", "2015-06-08", tick("KMI30", [
    ("ENGRO", "Engro Corporation Ltd.", "NML", "Nishat Mills Ltd."),
    ("DAWH", "Dawood Hercules Corp Ltd.", "DGKC", "D.G. Khan Cement Co Ltd."),
    ("FATIMA", "Fatima Fertilizer Co Ltd.", "PKGS", "Packages Ltd."),
    ("EFERT", "Engro Fertilizers Ltd.", "NATF", "National Foods Ltd."),
    ("EFOODS", "Engro Foods Ltd.", "ABOT", "Abbott Lab. Pakistan Ltd."),
    ("PAEL", "Pak Elektron Ltd.", "MTL", "Millat Tractors Ltd."),
    ("PSMC", "Pak Suzuki Motor Company", "APL", "Attock Petroleum Ltd"),
    ("HCAR", "Honda Atlas Car Ltd.", "NRL", "Nat. Refinery Ltd."),
    ("HASCOL", "Hascol Petroleum Ltd.", "TREET", "Treet Corp. Ltd."),
]))
add("69994", "2015-10-01", kse100([
    ("Dolmen City REIT", "Shezan International Limited", "Sector Based / Market Capitalization Based"),
    ("Associated Services Limited", "Atlas Battery Limited", "Sector Based / Market Capitalization Based"),
    ("Ferozsons Laboratories Limited", "Atlas Honda Limited", "Market Capitalization Based"),
    ("Lalpir Power Limited", "Kohinoor Energy Limited", "Market Capitalization Based"),
]))
add("74236", "2015-12-28", tick("KMI30", [
    ("DGKC", "D.G. Cement", "PSO", "P.S.O."),
    ("NML", "Nishat Mills", "PAKCEM", "Pakcem Ltd"),
    ("MTL", "Millat Trac.", "KAPCO", "Kot Addu Power"),
    ("TREET", "Treet Corp.", "KOHC", "Kohat Cement"),
]))
add("76768", "2016-02-15", excl("KSE30", [
    ("Adamjee Insurance Company Limited", "Honda Atlas Cars (Pakistan) Limited", ""),
    ("Byco Petroleum Pakistan Limited", "Jahangir Siddiqui & Co. Limited", ""),
    ("Dawood Hercules Corporation Limited", "Pakistan Telecommunication Company Limited", ""),
    ("Sui Southern Gas Company Limited", "Pioneer Cement Limited", ""),
]))
add("79044", "2016-04-01", kse100([
    ("Saif Power Limited", "Gul Ahmed Textile Mills Limited", MCB),
    ("Hascol Petroleum Limited", "Archroma Pakistan Limited", MCB),
    ("Pakistan International Container Terminal Limited", "Attock Cement Pakistan Limited", MCB),
    ("Cherat Packaging Limited", "Pakcem Limited", MCB),
]))
add("083246", "2016-06-29", excl("KMI30", [
    ("BYCO Petroleum Pakistan Ltd", "Fauji Fertilizer Company Ltd", ""),
    ("Kot Addu Power Company Ltd", "Fauji Fertilizer Bin Qasim Limited", ""),
    ("Sui Southern Gas Company Ltd", "Shell Pakistan Ltd", ""),
    ("Sui Northern Gas Pipeline Ltd", "Millat Tractors Limited", ""),
]))
add("84882", "2016-08-15", excl("KSE30", [
    ("Attock Refinery Limited", "Adamjee Insurance Company Limited", ""),
    ("Honda Atlas Cars (Pakistan) Limited", "Byco Petroleum Pakistan", ""),
    ("Sui Northern Gas Pipelines", "Sui Southern Company Limited", ""),
]))
add("86223", "2016-10-03", kse100([
    ("Philip Morris (Pakistan) Limited", "Lalpir Power Limited", MCB),
    ("Crescent Steel & Allied Products Limited", "Pakgen Power Limited", MCB),
    ("Bestway Cement Limited", "EFU Life Assurance Limited", MCB),
]))
add("91585", "2017-01-09", excl("KMI30", [
    ("Oil & Gas Development Co. Ltd", "BYCO Petroleum Pakistan Ltd", "REVISED"),
    ("National Refinery Ltd", "Kot Addu Power Company Ltd", "REVISED"),
    ("Ghandhara Industries Ltd", "D.G. Khan Cement Company Ltd", "REVISED"),
    ("Ghandhara Nissan Ltd", "Nishat Mills Ltd", "REVISED"),
    ("Packages Ltd", "Treet Corporation", "REVISED"),
], in_reason="REVISED"))
add("94294", "2017-02-15", excl("KSE30", [
    ("National Refinery Limited", "Fauji Fertilizer Bin Qasim Limited", ""),
]))
add("096346", "2017-04-03", kse100([
    ("Crescent Jute Products Limited", "Associated Services Limited", SBR),
    ("Attock Cement Pakistan Limited", "Rafhan Maize Products Co. Limited", MCB),
]))
add("100115", "2017-06-30", excl("KMI30", [
    ("D.G. Khan Cement Co., Ltd", "Pak Suzuki Company Ltd", ""),
    ("Nishat Mills Ltd", "Fatima Fertilizers Ltd", ""),
    ("Hi-Tech Lubricant Ltd", "Ghandhara Nissan Ltd", ""),
    ("Millat Tractors Ltd", "Pakistan Telecommunication Ltd", ""),
]))
add("101558", "2017-08-15", excl("KSE30", [
    ("International Steels Limited", "Dawood Hercules Corporation Limited", ""),
    ("Millat Tractors Limited", "Mari Petroleum Company Limited", ""),
]))
add("103102", "2017-10-02", kse100([
    ("Gadoon Textile Mills Limited", "Indus Dyeing & Manufacturing Company Limited", SBR),
    ("International Industries Limited", "Ferozsons Laboratories Limited", MCB),
    ("Amreli Steels Limited", "Arif Habib Corporation Limited", MCB),
    ("Atlas Honda Limited", "Service Industries Limited", MCB),
]))
add("107769", "2018-01-02", excl("KMI30", [
    ("International Steels Ltd", "Cherat Cement Company Ltd", R(32)),
    ("Engro Polymer & Chemicals Ltd", "Pioneer Cement Ltd", R(36)),
    ("Kot Addu Power Company Limited", "Hi-Tech Lubricants Limited", R(41)),
    ("Attock Petroleum Ltd", "Ghandhara Industries Ltd", R(45)),
    ("International Industries Ltd", "Honda Atlas Cars (Pakistan) Ltd", NC),
    ("Treet Corporation Ltd", "Engro Foods Limited", NC),
]))
add("109843", "2018-02-15", excl("KSE30", [
    ("Sui Southern Gas Company Limited", "Engro Foods Limited", ""),
    ("Engro Polymer & Chemicals Limited", "K-Electric Limited", ""),
    ("Bank AL Habib Limited", "Hascol Petroleum Limited", ""),
    ("Aisha Steel Mills Limited", "Honda Atlas Cars (Pakistan) Limited", ""),
]))
add("112040", "2018-04-02", kse100([
    ("First Habib Modaraba", "Allied Rental Modaraba", SBR),
    ("Pakistan Stock Exchange Limited", "Crescent Jute Products Limited", SBR),
    ("Unity Foods Limited", "Punjab Oil Mills Limited", SBR),
    ("Engro Polymer & Chemicals Limited", "Jubilee General Insurance Company Limited", MCB),
    ("Agriauto Industries Limited", "Cherat Packaging Limited", MCB),
    ("Archroma Pakistan Limited", "Soneri Bank Limited", MCB),
    ("Systems Limited", "Attock Cement Pakistan Limited", MCB),
]))
add("115468", "2018-06-29", excl("KMI30", [
    ("Pak Suzuki Motor Co Ltd", "GlaxoSmithKline Pakistan Ltd", R(31)),
    ("Engro Foods Ltd", "Treet Corporation Ltd", R(32)),
    ("Mughal Iron & Steel Ind. Ltd", "Attock Petroleum Ltd", R(34)),
    ("Pakistan Refinery Ltd", "Kot Addu Power Company Limited", NC),
]))
add("116819", "2018-09-17", excl("KSE30", [
    ("Bank Alfalah Limited", "Maple Leaf Cement Factory Limited", ""),
    ("Honda Atlas Cars (Pakistan) Limited", "National Refinery Limited", ""),
    ("Mari Petroleum Company Limited", "Aisha Steel Mills Limited", ""),
]))
add("118231", "2018-10-01", kse100([
    ("Gatron (Industries) Limited", "Ibrahim Fibres Limited", SBR),
    ("Shakarganj Limited", "JDW Sugar Mills Limited", SBR),
    ("Byco Petroleum Pakistan Limited", "Crescent Steel & Allied Products Limited", MCB),
    ("GlaxoSmithKline Consumer HealthCare Limited", "Jahangir Siddiqui & Co. Limited", MCB),
    ("Aisha Steel Mills Limited", "Nishat Power Limited", MCB),
]))
add("123703", "2018-12-28", excl("KMI30", [
    ("Pakistan State Oil Co. Ltd", "Mughal Iron & Steels Ind Ltd.", NC),
    ("Pakistan Int'l Bulk Terminal Ltd", "Pakistan Refinery Ltd", R(50)),
    ("Lotte Chemical Pakistan Ltd", "Pak Suzuki Motor Co. Ltd", R(34)),
    ("Byco Petroleum Pakistan Ltd", "Millat Tractor Ltd.", NC),
    ("Shell (Pakistan) Ltd", "Dawood Hercules Corporation", R(36)),
]))
add("125623", "2019-03-15", excl("KSE30", [
    ("The Bank of Punjab", "Sui Southern Gas Company Limited", ""),
    ("Maple Leaf Cement Factory Limited", "Honda Atlas Cars (Pakistan) Limited", ""),
]))
add("127823", "2019-04-01", kse100([
    ("Ibrahim Fibres Limited", "Gatron (Industries) Limited", SBR),
    ("Service Industries Limited", "Bata Pakistan Limited", SBR),
    ("AGP Limited", "Pakistan International Container Terminal Limited", MCB),
    ("Lotte Chemical Pakistan Limited", "Amreli Steels Limited", MCB),
    ("Gul Ahmed Textile Mills Limited", "Hum Network Limited", MCB),
    ("Fauji Foods Limited", "Aisha Steel Mills Limited", MCB),
]))
add("132207", "2019-07-15", excl("KMI30", [
    ("Millat Tractor Ltd.", "International Ind. Ltd", R(32)),
    ("Attock Petroleum Ltd", "National Refinery Ltd", R(33)),
    ("AGP Ltd", "Engro Foods Ltd", R(34)),
    ("Meezan Bank Ltd", "Shell (Pakistan) Ltd", R(36)),
    ("Honda Atlas Car Ltd", "Pakistan State Oil Ltd", NC),
    ("Dawood Hercules Corporation", "Byco Petroleum Pakistan Ltd", NC),
    ("Thal Ltd", "The Hub Power Company Ltd", "Shariah status not ascertained (non-disclosure)"),
]))
add("133547", "2019-09-16", excl("KSE30", [
    ("Lotte Chemicals Ltd", "Attock Refinery Ltd", ""),
    ("Meezan Bank Ltd", "International Steel Ltd", ""),
]))
add("134602", "2019-10-01", kse100([
    ("Indus Dyeing & Manufacturing Ltd", "Gadoon Textile Mills Ltd", SBR),
    ("J.D.W Sugar Mills Ltd", "Shakarganj Limited", SBR),
    ("Feroze 1888 Mills Ltd", "National Refinery Ltd", MCB),
    ("Azgard Nine Ltd", "Fauji Foods Ltd", MCB),
]))
add("140704", "2019-12-31", excl("KMI30", [
    ("The Hub Power Company Ltd", "Attock Petroleum Ltd", R(31)),
    ("Pakistan State Oil Company Ltd", "Hascol Petroleum Ltd", R(34)),
    ("Frieslandcampina Engro Pakistan Ltd", "Packages Ltd", R(37)),
    ("Pak Suzuki Motor Company Ltd", "AGP Ltd", R(44)),
    ("NetSol Technologies Ltd", "Pakistan International Bulk Terminal Ltd", NC),
    ("Unity Foods Limited", "Thal Ltd", NC),
]))
add("143019", "2020-03-13", excl("KSE30", [
    ("Attock Refinery Limited", "The Bank of Punjab", ""),
    ("International Steel Limited", "Kot Addu Power Company Limited", ""),
]))
add("144797", "2020-04-01", kse100([
    ("Yousaf Weaving Mills Ltd", "Shahtaj Textile Limited", SBR),
    ("Interloop Limited", "Nishat Chunian Power Limited", MCB),
    ("Highnoon Laboratories", "Bestway Cement Limited", MCB),
]))
add("149641", "2020-07-13", excl("KMI30", [
    ("Cherat Cement Company Ltd", "The Hub Power Company Ltd", NC),
    ("Indus Motor Company Ltd", "Pak Suzuki Motor Company Ltd", NC),
    ("Systems Limited", "Dawood Hercules Corporation Ltd", NC),
    ("National Refinery Ltd", "Sui Southern Gas Co Ltd", R(31)),
    ("Hascol Petroleum Ltd", "Frieslandcampina Engro Foods Ltd", R(40)),
]))
add("150518", "2020-09-15", excl("KSE30", [
    ("The Bank of Punjab", "Attock Refinery Limited", R(32)),
    ("Cherat Cement Company Limited", "Millat Tractors Limited", R(33)),
    ("Hascol Petroleum Limited", "Engro Polymer & Chemicals Ltd.", R(34)),
    ("Unity Foods Limited", "Lotte Chemical Pakistan Ltd.", R(39)),
]))
add("152395", "2020-10-01", kse100([
    ("Shahtaj Textile Limited", "Yousaf Weaving Mills Limited", SBR),
    ("Gadoon Textile Mills Limited", "Indus Dyeing & Manufacturing Co. Limited", SBR),
    ("Gatron (Industries) Limited", "Ibrahim Fibres Limited", SBR),
]))
add("158191", "2020-12-21", excl("KMI30", [
    ("GlaxoSmithKline Pakistan Ltd", "Lotte Chemical Pakistan Ltd.", NC),
    ("Kohat Cement Company Ltd", "Hascol Petroleum Ltd.", NC),
    ("ICI Pakistan Limited", "Indus Motor Company Ltd.", NC),
    ("Abbott Lab (Pakistan) Ltd", "Systems Limited", NC),
    ("Packages Limited", "National Refinery Ltd.", R(32)),
    ("International Industries Ltd", "NetSol Technologies Ltd.", R(38)),
]))
add("160384", "2021-03-15", excl("KSE30", [
    ("Attock Refinery Limited", "Fauji Cement Company Limited", R(31)),
    ("Systems Limited", "Hascol Petroleum Limited", R(32)),
    ("Ghandhara Industries Limited", "Sui Northern Gas Pipelines Limited", R(34)),
    ("Pioneer Cement Limited", "National Bank of Pakistan", R(35)),
    ("Kot Addu Power Company Limited", "Bank Alfalah Limited", R(39)),
    ("Dawood Hercules Corporation Limited", "The Bank of Punjab", R(47)),
]))
add("163214", "2021-04-01", kse100([
    ("Yousaf Weaving Mills Limited", "Shahtaj Textile Limited", SBR),
    ("Ibrahim Fibres Limited", "Gatron (Industries) Limited", SBR),
    ("National Refinery Limited", "Philip Morris (Pakistan) Limited", SBR),
    ("Unity Foods Limited", "Glaxo SmithKline Consumer Healthcare Pakistan Limited", SBR),
    ("Century Paper & Board Mills Limited", "Saif Power Limited", MCB),
]))
add("168338", "2021-06-28", excl("KMI30", [
    ("Hub Power Company Limited", "Abbott Laboratories Pak Ltd.", R(37)),
    ("Systems Limited", "Kohat Cement Co. Ltd.", R(39)),
    ("Ghandhara Industries Limited", "ICI Pakistan Limited", R(43)),
    ("Avanceon Limited", "K-Electric Limited", R(44)),
    ("Pakistan International Bulk Terminal Limited", "Packages Ltd.", R(45)),
    ("National Refinery Limited", "Glaxo SmithKline Pakistan Ltd.", R(47)),
]))
add("170014", "2021-09-15", excl("KSE30", [
    ("Pakistan Refinery Limited", "Cherat Cement Company Limited", R(32)),
    ("National Refinery Limited", "Nishat Mills Limited", R(33)),
    ("International Industries Limited", "Pak Elektron Limited", R(34)),
    ("Engro Polymer & Chemicals Limited", "Ghandhara Industries Limited", R(37)),
    ("Avanceon Limited", "Dawood Hercules Corporation Limited", "Not eligible"),
]))
add("171838", "2021-10-01", kse100([
    ("Shakarganj Limited", "JDW Sugar Mills Limited", SBR),
    ("Aisha Steel Mills Limited", "Jubilee Life Insurance Company Limited", MCB),
    ("Avanceon Limited", "Agriauto Industries Limited", MCB),
    ("Jahangir Siddiqui & Co. Limited", "Sui Southern Gas Company Limited", MCB),
    ("Mughal Iron & Steel Industries Limited", "Hascol Petroleum Limited", "Company quoted on Defaulters Segment"),
]))
add("178582", "2021-12-20", excl("KMI30", [
    ("Pioneer Cement Ltd", "Pakistan Intl. Bulk Terminal Ltd.", "REVISED; " + R(33)),
    ("Byco Petroleum Pakistan Ltd", "Sui Northern Gas Pipe Line Ltd.", "REVISED; " + R(35)),
    ("Azgard Nine Ltd", "Honda Atlas Cars (Pak) Ltd.", "REVISED; " + R(37)),
], in_reason="REVISED"))
add("180575", "2022-03-15", excl("KSE30", [
    ("Millat Tractors Limited", "Pioneer Cement Limited", R(31)),
    ("Ghani Global Holdings Limited", "International Industries Limited", R(33)),
    ("Cnergyico PK Limited", "International Steels Limited", R(49)),
    ("NetSol Technologies Limited", "Pakistan Refinery Limited", R(70)),
]))
add("183692", "2022-04-01", kse100([
    ("Pak-Gulf Leasing Company", "Orix Leasing Pakistan Limited", SBR),
    ("Tariq Glass Industries Limited", "Feroze1888 Mills Limited", MCB),
    ("Javedan Corporation Limited", "Jahangir Siddiqui & Company Limited", MCB),
]))
KMI_2022H1 = [
    ("Ghani Global Holdings Limited", "Fauji Cement Co. Limited", 33),
    ("Treet Corporation Limited", "Ghandhara Industries Limited", 35),
    ("Telecard Limited", "Pak Elektron Limited", 36),
    ("Sui Northern Gas Pipelines Limited", "International Steels Limited", 37),
    ("Dawood Hercules Corporation Limited", "Azgard Nine Limited", 38),
]
add("189282", "2022-07-08", excl("KMI30", [(i, o, R(n)) for i, o, n in KMI_2022H1]))
# 189483: page 1 is a date-change cover note; the revised PSX/N-625 table is the annexure (page 2).
add("189483", "2022-07-13", excl("KMI30", [(i, o, "REVISED; " + R(n)) for i, o, n in KMI_2022H1],
                                 in_reason="REVISED"))
add("190138", "2022-09-15", excl("KSE30", [
    ("Treet Corporation Limited", "Cnergyico PK Limited", R(31)),
    ("TPL Properties Limited", "The Searle Company Limited", R(37)),
    ("Telecard Limited", "NetSol Technologies Limited", R(41)),
]))
add("192163", "2022-10-03", kse100([
    ("Air Link Communication Ltd", "Azgard Nine Ltd", MCB),
    ("Rafhan Maize Products Company Ltd", "Aisha Steel Mills Ltd", MCB),
    ("Unilever Pakistan Foods Ltd", "IGI Holdings Ltd", MCB),
]))
add("199661", "2022-12-30", excl("KMI30", [
    ("TPL Properties Limited", "Hub Power Company Limited", NC),
    ("Fauji Cement Co. Limited", "Sui Northern Gas Pipe Line Ltd.", NT),
    ("Pak Elektron Limited", "International Industries Ltd.", NT),
]))
add("201323", "2023-03-15", excl("KSE30", [
    ("Pakistan Refinery Limited", "Ghani Global Holdings Limited", ""),
    ("NetSol Technologies Limited", "Maple Leaf Cement Factory Limited", ""),
    ("Sui Northern Gas Pipe Line Limited", "Telecard Limited", ""),
    ("Pak Elektron Limited", "Treet Corporation Limited", ""),
]))
add("204338", "2023-04-03", kse100([
    ("JDW Sugar Mills Ltd.", "Shakarganj Ltd", SBR),
    ("Pakistan Aluminum Beverage Cans Ltd.", "Nishat Chunian Ltd", MCB),
]))
add("211205", "2023-07-07", excl("KMI30", [
    ("Hub Power Company Limited", "Cnergyico PK Limited", NC),
    ("Pakistan Refinery Limited", "Ghani Global Holdings Limited", NT),
    ("NetSol Technologies Limited", "Nishat Mills Limited", NT),
    ("Sui Northern Gas Pipelines Limited", "Pakistan Oilfields Limited", NC),
    ("Attock Petroleum Limited", "The Searle Company Limited", NT),
    ("Lotte Chemical Pakistan Limited", "Telecard Limited", NT),
    ("Shell (Pakistan) Limited", "Treet Corporation Limited", NT),
]))
add("212654", "2023-09-15", tick("KSE30", [
    ("APL", "Attock Petroleum Limited", "NETSOL", "NetSol Technologies Limited"),
    ("BAFL", "Bank Alfalah Limited", "NRL", "National Refinery Limited"),
    ("CHCC", "Cherat Cement Company Limited", "PAEL", "Pak Elektron Limited"),
    ("FCCL", "Fauji Cement Company Limited", "PRL", "Pakistan Refinery Limited"),
    ("MLCF", "Maple Leaf Cement Factory Limited", "TPLP", "TPL Properties Limited"),
    ("PIOC", "Pioneer Cement Limited", "UNITY", "Unity Foods Limited"),
]))
add("215025", "2023-10-02", kse100([
    ("BankIslami Pakistan Limited", "Air Link Communication Limited", MCB),
    ("Bestway Cement Limited", "Atlas Honda Limited", MCB),
    ("Pakgen Power Limited", "Honda Atlas Cars (Pakistan) Limited", MCB),
    ("Saif Power Limited", "Pak Suzuki Motor Company Limited", MCB),
]))
add("222622", "2023-12-22", excl("KMI30", [
    ("Colgate-Palmolive (Pakistan) Limited", "Dawood Hercules Corporation Limited", NC),
    ("The Searle Company Limited", "NetSol Technologies Limited", NT),
    ("Cnergyico PK Limited", "Pak Elektron Limited", NT),
    ("Dolmen City REIT", "Shell Pakistan Limited", NT),
]))
add("224564", "2024-03-15", tick("KSE30", [
    ("NRL", "National Refinery Limited", "APL", "Attock Petroleum Limited"),
    ("SHEL", "Shell Pakistan Limited", "AVN", "Avanceon Limited"),
    ("PRL", "Pakistan Refinery Limited", "EPCL", "Engro Polymer & Chemicals Limited"),
    ("COLG", "Colgate-Palmolive (Pakistan) Limited", "FCCL", "Fauji Cement Company Limited"),
    ("SEARL", "The Searle Company Limited", "KAPCO", "Kot Addu Power Company Limited"),
    ("TPLP", "TPL Properties Limited", "PIOC", "Pioneer Cement Limited"),
]))
add("227567", "2024-04-01", kse100([
    ("Nishat Chunian Power Limited", "Archroma Pakistan Limited", MCB),
    ("Nishat Power Limited", "Gul Ahmed Textile Mills Limited", MCB),
    ("Habib Sugar Mills Limited", "JDW Sugar Mills Limited", SBR),
]))
add("232761", "2024-06-14", excl("KMI30", [
    ("Shell (Pakistan) Limited", "Attock Petroleum Limited", NT),
    ("Nishat Mills Limited", "Avanceon Limited", NT),
    ("Interloop Limited", "Cnergyico PK Limited", NT),
    ("NetSol Technologies Limited", "Colgate-Palmolive (Pakistan) Limited", NC),
    ("Faysal Bank Limited", "Lotte Chemical Pakistan Limited", NT),
    ("AirLink Communication Limited", "Oil & Gas Development Company Limited", NC),
]))
add("234730", "2024-09-16", tick("KSE30", [
    ("FFBL", "Fauji Fertilizer Bin Qasim Limited", "CHCC", "Cherat Cement Company Limited"),
    ("FCCL", "Fauji Cement Company Limited", "COLG", "Colgate-Palmolive (Pakistan) Limited"),
    ("SAZEW", "Sazgar Engineering Works Limited", "SHEL", "Shell Pakistan Limited"),
    ("PIOC", "Pioneer Cement Limited", "TPLP", "TPL Properties Limited"),
    ("PAEL", "Pak Elektron Limited", "TRG", "TRG Pakistan Limited"),
]))
add("236819", "2024-10-01", kse100([
    ("Kohinoor Spinning Mills Limited", "Gadoon Textile Mills Limited", SBR),
    ("JDW Sugar Mills Limited", "Habib Sugar Mills Limited", SBR),
    ("Sazgar Engineering Works Limited", "BankIslami Pakistan Limited", MCB),
    ("Air Link Communication Limited", "Century Paper & Board Mills Limited", MCB),
    ("Mehmood Textile Mills Limited", "Kohinoor Textile Mills Limited", MCB),
    ("Atlas Honda Limited", "Shifa International Hospitals Limited", MCB),
    ("Honda Atlas Cars (Pakistan) Limited", "Saif Power Limited", MCB),
]))
SP_FFBL = "Special; merger of FFBL into FFC"
add("244680", "2024-12-23", [
    ("P", "KSE100", "BankIslami Pakistan Limited", "", "Fauji Fertilizer Bin Qasim Limited", "FFBL", SP_FFBL, SP_FFBL),
    ("P", "KSE30", "Air Link Communication Limited", "", "Fauji Fertilizer Bin Qasim Limited", "FFBL", SP_FFBL, SP_FFBL),
])
add("244792", "2024-12-30", excl("KMI30", [
    ("Oil & Gas Development Co. Limited", "Cherat Cement Company Limited", NT),
    ("Sazgar Engineering Works", "Dolmen City REIT", NT),
    ("Pak Elektron Limited", "Interloop Limited", NT),
    ("Honda Atlas Cars (Pakistan) Limited", "NetSol Technologies Limited", NT),
    ("Fauji Foods Limited", "Nishat Mills Limited", NT),
    ("K-Electric Limited", "Shell Pakistan Limited", NT),
    ("Dawood Hercules Corporation Limited", "TPL Properties Limited", NT),
]))
SP_ENGRO = "Special; ENGRO-DAWH scheme of arrangement"
add("245360", "2025-01-06", [
    ("P", "KSE100", "Kohinoor Textile Mills Limited", "", "Engro Corporation Limited", "ENGRO", SP_ENGRO, SP_ENGRO),
    ("P", "KSE30", "Dawood Hercules Corporation Limited", "DAWH", "Engro Corporation Limited", "ENGRO", SP_ENGRO, SP_ENGRO),
    ("P", "KMI30", "Ghandhara Industries Limited", "", "Engro Corporation Limited", "ENGRO", SP_ENGRO, SP_ENGRO),
    # PSXDIV20 row (DAWH in, ENGRO out) skipped by spec.
])
add("246724", "2025-03-17", excl("KSE30", [
    ("Ghandhara Industries Limited", "Bank Alfalah Limited", ""),
    ("Ghandhara Automobiles Limited", "National Refinery Limited", ""),
    ("NetSol Technologies Limited", "Pioneer Cement Limited", ""),
    ("National Bank of Pakistan", "Pakistan Refinery Limited", ""),
    ("Dewan Farooque Motors Limited", "Sui Northern Gas Pipelines Limited", ""),
]))
# 249609: w.e.f. "first working day of April 2025 (subject to moon sighting)" -> no explicit date.
add("249609", "", [
    ("P", "KSE100", "TPL REIT Fund I", "", "BankIslami Pakistan Limited", "", SBR, MCB),
    ("P", "KSE100", "Gadoon Textile Mills Limited", "", "Kohinoor Spinning Mills Limited", "", SBR, SBR),
    ("P", "KSE100", "Agritech Limited", "", "Nishat Chunian Power Limited", "", MCB, MCB),
    ("P", "KSE100", "Hum Network Limited", "", "National Refinery Limited", "", MCB, MCB),
    ("P", "KSE100", "Haleon Pakistan Limited", "", "Wafi Energy Pakistan Limited", "", MCB, MCB),
])
add("254335", "2025-06-02", excl("KMI30", [
    ("Ghandhara Automobiles Limited", "Air Link Communication Limited", NC),
    ("NetSol Technologies Limited", "Engro Polymer & Chemicals Limited", NT),
    ("Octopus Digital Limited", "K-Electric Limited", NT),
    ("The Organic Meat Company Limited", "National Refinery Limited", NC),
    ("Avanceon Limited", "Unity Foods Limited", NT),
]))
add("257248", "2025-09-15", excl("KSE30", [
    ("Sui Northern Gas Pipelines Limited", "Air Link Communication Limited", ""),
    ("Pakistan Refinery Limited", "Dewan Farooque Motors Limited", ""),
    ("The Bank of Punjab", "Millat Tractors Limited", ""),
    ("Sui Southern Gas Company Limited", "NetSol Technologies Limited", ""),
]))
add("259330", "2025-10-01", kse100([
    ("S.S. Oil Mills Limited", "Punjab Oil Mills", SBR),
    ("Shifa International Hospitals Limited", "Avanceon Limited", MCB),
    ("DH Partners Limited", "EFU General Insurance Limited", MCB),
    ("Ghandhara Automobiles Limited", "Engro Polymer & Chemicals Limited", MCB),
    ("Sui Southern Gas Company Limited", "Frieslandcampina Engro Pakistan Limited", MCB),
    ("Ghandhara Industries Limited", "Mughal Iron & Steel Industries Limited", MCB),
    ("Citi Pharma Ltd.", "Nishat Power Limited", MCB),
    ("Fauji Foods Limited", "Agritech Limited", MCB),
]))
add("265733", "2025-11-24", excl("KMI30", [
    ("Sui Southern Gas Company Limited", "Octopus Digital Limited", NT),
    ("Fauji Fertilizer Company Limited", "Pioneer Cement Limited", NT),
    ("GlaxoSmithKline Pakistan", "Honda Atlas Cars (Pakistan) Limited", NT),
    ("National Refinery Limited", "NetSol Technologies Limited", NT),
    ("Air Link Communication Limited", "Faysal Bank Limited", NT),
    ("Citi Pharma Limited", "Avanceon Limited", NT),
    ("Cnergyico PK Limited", "The Organic Meat Company Limited", NT),
]))
add("269514", "2026-03-16", excl("KSE30", [
    ("Air Link Communication Limited", "Bank AL Habib Limited", ""),
    ("National Refinery Limited", "Pakistan Refinery Limited", ""),
]))
add("272534", "2026-04-01", kse100([
    ("Arif Habib Corporation Limited", "Unity Foods Limited", MCB),
    ("Power Cement Limited", "Pakgen Power Limited", MCB),
]))
SP_DHPL = "Special; DHPL suspension and delisting"
add("272946", "2026-03-25", [
    ("P", "KSE100", "Nishat Power Limited", "", "DH Partners Limited", "DHPL", SP_DHPL, SP_DHPL),
])
add("277332", "2026-05-25", excl("KMI30", [
    ("Nishat Mills Limited", "Cnergyico PK Limited", NT),
    ("Treet Corporation Limited", "GlaxoSmithKline Pakistan Limited", NT),
    ("Honda Atlas Cars (Pakistan) Limited", "Millat Tractors Limited", NT),
]))
add("280653", "2026-09-15", excl("KSE30", [
    ("Pakistan Telecommunication Company Ltd", "Air Link Communication Limited", ""),
    ("Bank Alfalah Limited", "Ghandhara Automobiles Limited", ""),
    ("K-Electric Limited", "Ghandhara Industries Limited", ""),
    ("Fatima Fertilizer Company Limited", "Sui Southern Gas Company Limited", ""),
]))
add("282746", "2026-10-01", kse100([
    ("Image Pakistan Limited", "Hum Network Limited", SBR),
    ("Thatta Cement Company Limited", "Mehmood Textile Mills Limited", MCB),
    ("Nishat Chunian Power Limited", "Pakistan Aluminium Beverage Cans Limited", MCB),
    ("Bank Makramah Limited", "Rafhan Maize Products Company Limited", MCB),
]))


def main():
    meta = {}
    with open(os.path.join(SRC, "index_notices.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            meta[r["doc_id"]] = r["announced_at"]

    seen = set()
    rows = []
    for doc_id, eff, entries in NOTICES:
        assert doc_id in meta, doc_id
        assert doc_id not in seen, doc_id
        seen.add(doc_id)
        for _, index, iname, isym, oname, osym, ir, orr in entries:
            assert index in ("KSE100", "KSE30", "KMI30")
            for direction, name, sym, reason in (("in", iname, isym, ir), ("out", oname, osym, orr)):
                name = " ".join(name.split())
                rows.append({
                    "doc_id": doc_id,
                    "announced_at": meta[doc_id],
                    "index": index,
                    "effective_date": eff,
                    "direction": direction,
                    "company": name,
                    "symbol_in_text": sym,
                    "reason": reason,
                })
    missing = set(meta) - seen
    print("notices without rows:", sorted(missing))

    # sanity: no duplicate company/direction/index within a notice
    keys = [(r["doc_id"], r["index"], r["direction"], r["company"]) for r in rows]
    dups = {k for k in keys if keys.count(k) > 1}
    assert not dups, dups

    order = {d: i for i, d in enumerate(meta)}
    rows.sort(key=lambda r: (order[r["doc_id"]], ["KSE100", "KSE30", "KMI30"].index(r["index"])))
    cols = ["doc_id", "announced_at", "index", "effective_date", "direction", "company", "symbol_in_text", "reason"]
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print("total rows:", len(rows))
    c = Counter((r["index"], r["direction"]) for r in rows)
    for k in sorted(c):
        print(k, c[k])


if __name__ == "__main__":
    main()
