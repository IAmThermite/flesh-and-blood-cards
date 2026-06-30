import { createPrintingDictionary, updateCardLegality } from './functions/index.js'

let printingDictionary = await createPrintingDictionary()
await updateCardLegality(printingDictionary)