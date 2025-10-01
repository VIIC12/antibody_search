# ABDB V3.0 Tests

Test suite for validating V3.0 against V1.0 and ensuring correctness.

## 📋 Test Plan

### Phase 1: Proof of Concept ✅
- [x] Data conversion (10 files)
- [x] Search engine initialization
- [x] Basic queries (IGHV, IGHD, IGHJ)
- [x] Statistics mode
- [x] Full results mode
- [x] Performance benchmarks

See **[../docs/TEST_RESULTS.md](../docs/TEST_RESULTS.md)** for results.

### Phase 2: Validation (TBD)
- [ ] Compare results with V1.0 (same queries, same results)
- [ ] Edge case testing (empty results, large results, etc.)
- [ ] Stress testing (full database, concurrent users)
- [ ] Data integrity checks (all sequences preserved)

### Phase 3: Integration (TBD)
- [ ] End-to-end web interface testing
- [ ] CSV export validation
- [ ] Docker deployment testing
- [ ] Performance regression tests

## 🧪 Planned Test Files

```
tests/
├── README.md                      # This file
├── test_conversion.py             # Test CSV.gz → Parquet conversion
├── test_search_engine.py          # Test DuckDB query engine
├── test_validation_vs_v1.py       # Compare with V1.0 results
├── test_performance.py            # Benchmark tests
├── test_integration.py            # End-to-end tests
└── fixtures/                      # Test data and fixtures
    ├── sample_data/               # Small test datasets
    └── expected_results/          # Known good results
```

## 🚀 Running Tests (Future)

```bash
# Install test dependencies
pip install pytest pytest-benchmark pytest-cov

# Run all tests
pytest tests/

# Run specific test
pytest tests/test_search_engine.py

# Run with coverage
pytest --cov=src tests/

# Run benchmarks
pytest tests/test_performance.py --benchmark-only
```

## ✅ Manual Validation Checklist

Current validation approach (until automated tests are built):

### Data Conversion
- [x] All files convert without errors
- [x] Row counts match (648,609 sequences)
- [x] No data loss (spot check sequences)
- [x] Metadata preserved (subjects, isotypes)
- [x] File sizes reasonable (49.6x compression)

### Search Functionality
- [x] Simple gene search (IGHV3-)
- [x] Specific gene search (IGHV3-23)
- [x] Multiple genes (3-20|3-22)
- [x] CDRH3 length filtering
- [x] Motif pattern matching
- [x] Full results retrieval
- [x] CSV export works

### Performance
- [x] Sub-second statistics queries
- [x] Fast full results (< 0.1s for 100 results)
- [x] Low memory usage (< 500 MB)
- [x] Scales with data size

### Comparison with V1.0 (Manual)
- [ ] Run identical query in both versions
- [ ] Verify hit counts match
- [ ] Verify same subjects found
- [ ] Verify same sequences (sample)
- [ ] Document any differences

## 🎯 Test Priorities

### High Priority (Phase 2)
1. **Validation against V1.0** - Most important!
   - Same results for same queries
   - No data loss
   - Correct statistics

2. **Edge Cases**
   - Empty result sets
   - Very large result sets
   - Invalid input handling

3. **Performance Benchmarks**
   - Document speed improvements
   - Memory usage profiles
   - Scaling characteristics

### Medium Priority (Phase 3)
4. **Integration Tests**
   - Web interface functionality
   - Export features
   - Error handling

5. **Regression Tests**
   - Prevent performance degradation
   - Ensure compatibility

### Low Priority (Phase 4)
6. **Load Testing**
   - Concurrent user simulation
   - Resource limits
   - Stress testing

## 📊 Current Test Results

See **[../docs/TEST_RESULTS.md](../docs/TEST_RESULTS.md)** for detailed results.

**Summary:**
- ✅ 10 files converted successfully
- ✅ 648,609 sequences indexed
- ✅ Search time: 0.01s (vs hours in V1.0)
- ✅ All functional tests passed

## 🔨 TODO: Automated Tests

### Quick Validation Test
```python
# tests/test_quick_validation.py
def test_v1_vs_v3_ighv3_search():
    """Compare IGHV3- search results between V1.0 and V3.0"""
    # Run same query in both versions
    # Compare hit counts, subjects, sample sequences
    # Assert results match within tolerance
    pass
```

### Performance Benchmark
```python
# tests/test_performance.py
def test_search_performance(benchmark):
    """Benchmark search performance"""
    engine = AntibodySearchEngine()
    result = benchmark(engine.search, ighv="3-23")
    assert result[1]['search_time'] < 1.0  # Sub-second
```

## 🆘 Contributing Tests

When adding tests:
1. Follow pytest conventions
2. Include docstrings
3. Use fixtures for test data
4. Document expected vs actual behavior
5. Update this README

## 📞 Contact

Questions about tests? Contact tom.schlegel@uni-leipzig.de

---

**Status**: Planned (automated tests TBD)  
**Manual validation**: ✅ Complete  
**Automated tests**: ⏳ Coming in Phase 2

