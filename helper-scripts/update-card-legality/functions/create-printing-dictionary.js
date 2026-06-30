import * as fs from 'fs'
import * as csv from 'csv'

// Set an index to null to omit generation for the associated unique ID
export const createPrintingDictionary = () => {
    return new Promise((resolve, reject) => {
        const inputCSV = `../../csvs/english/card-printing.csv`

        const readStream = fs.createReadStream(inputCSV)
        const csvStream = csv.parse({ delimiter: "\t" })
        const stringifier = csv.stringify({ delimiter: "\t" });

        // Get printings

        var printings = {}

        var headerRead = false

        var uniqueIdIndex = 0
        var cardUniqueIdIndex = 1
        var cardIdIndex = 4
        var rarityIndex = 8

        csvStream.on("data", function(data) {
            // Skip header
            if (!headerRead) {
                headerRead = true
                stringifier.write(data)
                return
            }

            // Card Unique ID

            // current card data
            var uniqueId = data[uniqueIdIndex]
            var cardUniqueId = data[cardUniqueIdIndex]
            var cardId = data[cardIdIndex]
            var rarity = data[rarityIndex]

            if (printings[cardUniqueId] == undefined) {
                printings[cardUniqueId] = []
            }

            printings[cardUniqueId].push({
                uniqueId,
                cardId,
                rarity
            })
        })
        .on('end', () => {
            resolve(printings)
        })
        .on("error", function (error) {
            console.log(error.message)
            reject()
        })

        readStream.pipe(csvStream)
    })
}