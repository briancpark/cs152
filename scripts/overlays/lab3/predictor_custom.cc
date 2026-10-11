// Custom software branch predictor from the Lab 3 report (Problem 4.1).
// Installed over generators/boom/src/main/resources/csrc/predictor_sw.cc by
// run_labs.sh when building the CS152SWPredBoomConfig "custom" variant.
#define BIMODAL_TABLE_SIZE 1024
#define BIMODAL_HISTORY_BITS 4
#define MAX_COUNTER 3

#include <stdint.h>
#include <stdio.h>

int bimodal_table[BIMODAL_TABLE_SIZE];

extern "C" void initialize_branch_predictor() {
    for (int i = 0; i < BIMODAL_TABLE_SIZE; i++)
        bimodal_table[i] = 0;
}

extern "C" void predict_branch(unsigned long long ip, unsigned long long hist, unsigned char *pred)
{
    uint32_t hash = ip % BIMODAL_TABLE_SIZE & 31;
    uint32_t update = hash >> BIMODAL_HISTORY_BITS;
    update = ((update ^ hist) % 32) << BIMODAL_HISTORY_BITS;
    hash = ((hash & 31) | update) % BIMODAL_TABLE_SIZE;

    *pred = (bimodal_table[hash] >= ((MAX_COUNTER + 1)/2)) ? 1 : 0;
}

extern "C" void update_branch(unsigned long long ip, unsigned long long hist, unsigned char taken){
    uint32_t hash = ip % BIMODAL_TABLE_SIZE;
    uint32_t update = hash >> BIMODAL_HISTORY_BITS;
    update = ((update ^ hist) % 32) << BIMODAL_HISTORY_BITS;
    hash = ((hash & 31) | update) % BIMODAL_TABLE_SIZE;

    if (taken && (bimodal_table[hash] < MAX_COUNTER))
        bimodal_table[hash]++;
    else if ((taken == 0) && (bimodal_table[hash] > 0))
        bimodal_table[hash]--;
}
