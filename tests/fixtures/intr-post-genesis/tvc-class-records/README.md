# TVC-class records (sealed examples, not current state)

These four records are byte-for-byte copies of the kit records for these paths as sealed on StegVerse-org/.github main 98556a33 (132 ledgered). At that point SV-011's ledger had no public route, so the paths were held on the TV/TVC route (TVC_PRIVATE_SOURCE_READ / TVC_PRIVATE_DESTINATION_READ, six fields).

After SV-011 joined the mesh (SV-011/.github#26 plus the twelve inbound rows), every one of the 156 declared paths is DESTINATION_RECEIPT_LEDGERED, so no live record is left in a TVC class. The kit test uses these sealed examples to keep the class rules exercised: a TVC record must not be promoted to ALLOW, and must not carry destination_receipts. They are not ledgered and not authentic, and no verifier reads them as state.
