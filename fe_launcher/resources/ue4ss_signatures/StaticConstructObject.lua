-- StaticConstructObject_Internal — Fading Echo Demo (UE_YGRO, fork UE 5.6.1 "EmeteriaDepot")
--
-- Motif derive du symbole PDB :
--   ?StaticConstructObject_Internal@@YAPEAVUObject@@AEBUFStaticConstructObjectParameters@@@Z
--
-- Verifie sur les deux builds (1 seul match dans .text a chaque fois) :
--   build 16/06 (174 949 888 o, PDB 69A3353C-...) -> VA 0x141590A90  <- adresse confirmee par le PDB
--   build 15/07 (176 570 880 o, PDB 1B8B2CC1-...) -> VA 0x1415FB9A0  <- la demo actuelle
--
-- Les 4 octets joker apres "48 8B 05" sont l'offset RIP-relatif vers le security cookie :
-- c'est le seul endroit ou les deux builds different (3 octets sur 128).

function Register()
    return "4C 8B DC 55 53 41 56 49 8D AB 28 FE FF FF 48 81 EC C0 02 00 00 48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 85 A0 01 00 00 8B 41 70 33 DB 49 89 73 10"
end

function OnMatchFound(MatchAddress)
    -- Le motif commence au premier octet du prologue : l'adresse du match EST la fonction.
    return MatchAddress
end
