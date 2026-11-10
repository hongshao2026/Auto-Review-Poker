#pragma once

void probe_hot_buckets() {
    using namespace hrc_hot_bucket;
    const double p[] = {.25, .5, .25};
    const double q[] = {-2, 6, 1};
    auto init = [](Node& node, uint64_t inherited) {
        node.k = 3;
        node.buckets = 169;
        node.unlocked_read = true;
        node.init();
        node.updates = inherited;
        node.raw[0] = double(inherited);
    };
    auto check = [](bool ok, const char* message) {
        if (!ok) throw std::runtime_error(message);
    };

    for (uint64_t inherited : {uint64_t(0), uint64_t(1700000000)}) {
        Node baseline, striped;
        init(baseline, inherited);
        init(striped, inherited);
        Random baseline_rng(42), striped_rng(42);
        HotNode hot;
        WorkerNode worker;
        hot.worker_count = 1;
        hot.workers[0] = &worker;
        hot.initial_updates = inherited;
        for (int i = 0; i < 100000; ++i) {
            const int bucket = (i * 31) % striped.buckets;
            baseline.update(baseline_rng, bucket, p, q, 1, 1);
            update(striped, striped_rng, hot, worker, bucket, p, q);
        }
        striped.updates = hot.total_updates();
        check(baseline.raw == striped.raw && baseline.visits == striped.visits &&
              baseline.updates == striped.updates &&
              std::equal(baseline_rng.s, baseline_rng.s + 4, striped_rng.s), "Serial bucket parity");
    }

    constexpr int workers = 20;
    constexpr int count = 16000;
    Node node;
    init(node, 87000);
    HotNode hot;
    hot.initial_updates = node.updates;
    hot.worker_count = workers;
    std::array<WorkerNode, workers> states;
    std::array<std::thread, workers> threads;
    std::atomic<bool> start{false};
    std::atomic<bool> bad_publication{false};
    for (int id = 0; id < workers; ++id) hot.workers[id] = &states[id];
    for (int id = 0; id < workers; ++id) {
        threads[id] = std::thread([&, id] {
            Random rng(uint64_t(id + 1));
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            double previous = 0;
            for (int i = 0; i < count; ++i) {
                const int bucket = (i + id) % 169;
                update(node, rng, hot, states[id], bucket, p, q);
                const double published = hrc_unlocked_read::load(node.raw.data());
                if (published < previous || published > double(hot.initial_updates + workers * count))
                    bad_publication.store(true, std::memory_order_relaxed);
                previous = published;
            }
        });
    }
    start.store(true, std::memory_order_release);
    for (auto& thread : threads) thread.join();
    check(!bad_publication.load(), "Counter publication monotonicity");
    node.updates = hot.total_updates();
    check(node.updates == hot.initial_updates + workers * count, "Total updates");
    for (int bucket = 0; bucket < node.buckets; ++bucket) {
        uint64_t expected = 0;
        for (int id = 0; id < workers; ++id)
            for (int i = bucket; i < count + id; i += node.buckets)
                if (i >= id) ++expected;
        const auto average = node.average(bucket);
        const double weight = node.raw[average - 1];
        check(node.visits[bucket] == expected, "Per-bucket visits");
        check(node.raw[average] + node.raw[average + 1] + node.raw[average + 2] == weight &&
              weight >= double(expected) * double(hot.initial_updates), "Average bucket weight");
    }
    node.flush();
    check(node.raw[0] == double(node.updates), "Quiescent flush");
    std::cout << "{\"serial_parity\":true,\"workers\":20,\"parallel_updates\":320000,"
                 "\"per_bucket_visits\":true,\"monotonic_counter\":true,\"quiescent_flush\":true}\n";
}
