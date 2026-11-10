#pragma once
// Independently implemented exponential-race / Edgeworth MTT equity.
// Production calculation has no dependency on HRC classes, data or utilities.
// See research/HRC-MTT-EQUITY.md for the model and numerical domain.
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace hrc_mtt {
namespace detail {
constexpr double eps = std::numeric_limits<double>::epsilon();
constexpr double phi_scale = 0.3989422804014327;
inline constexpr std::array<double, 5> x1 = {0.9739065285171717, 0.8650633666889845, 0.6794095682990244, 0.4333953941292472, 0.14887433898163122};
inline constexpr std::array<double, 5> w10 = {0.06667134430868814, 0.1494513491505806, 0.21908636251598204, 0.26926671930999635, 0.29552422471475287};
inline constexpr std::array<double, 5> x2 = {0.9956571630258081, 0.9301574913557082, 0.7808177265864169, 0.5627571346686047, 0.2943928627014602};
inline constexpr std::array<double, 5> w21a = {0.032558162307964725, 0.07503967481091996, 0.10938715880229764, 0.13470921731147334, 0.14773910490133849};
inline constexpr std::array<double, 6> w21b = {0.011694638867371874, 0.054755896574351995, 0.0931254545836976, 0.12349197626206584, 0.14277593857706009, 0.1494455540029169};
inline constexpr std::array<double, 11> x3 = {0.999333360901932, 0.9874334029080889, 0.9548079348142663, 0.9001486957483283, 0.8251983149831141, 0.732148388989305, 0.6228479705377252, 0.4994795740710565, 0.36490166134658075, 0.2222549197766013, 0.07465061746138332};
inline constexpr std::array<double, 10> w43a = {0.016296734289666565, 0.0375228761208695, 0.05469490205825544, 0.06735541460947808, 0.07387019963239395, 0.005768556059769796, 0.027371890593248842, 0.04656082691042883, 0.06174499520144257, 0.07138726726869339};
inline constexpr std::array<double, 12> w43b = {0.001844477640212414, 0.010798689585891651, 0.021895363867795427, 0.032597463975345686, 0.04216313793519181, 0.050741939600184575, 0.05837939554261925, 0.06474640495144589, 0.06956619791235648, 0.07282444147183322, 0.07450775101417512, 0.07472214751740301};
inline constexpr std::array<double, 22> x4 = {0.9999029772627293, 0.9979898959866788, 0.9921754978606873, 0.9813581635727128, 0.9650576238583847, 0.9431676131336706, 0.9158064146855072, 0.8832216577713164, 0.8457107484624157, 0.8035576580352309, 0.7570057306854956, 0.7062732097873218, 0.6515894665011779, 0.5932233740579611, 0.531493605970832, 0.46676362304202285, 0.3994248478592188, 0.3298748771061883, 0.25850355920216156, 0.18569539656834666, 0.11184221317990747, 0.03735212339461987};
inline constexpr std::array<double, 21> w87a = {0.008148377384149173, 0.018761438201562824, 0.027347451050052287, 0.03367770731163793, 0.036935099820427905, 0.0028848724302115306, 0.013685946022712702, 0.02328041350288831, 0.03087249761171336, 0.03569363363941877, 0.0009152833452022414, 0.005399280219300471, 0.01094767960111893, 0.016298731696787336, 0.021081568889203834, 0.025370969769253827, 0.029189697756475754, 0.03237320246720279, 0.034783098950365146, 0.03641222073135179, 0.037253875503047706};
inline constexpr std::array<double, 23> w87b = {0.00027414556376207234, 0.0018071241550579428, 0.0040968692827591646, 0.006758290051847379, 0.009549957672201646, 0.012329447652244854, 0.015010447346388952, 0.01754896798624319, 0.019938037786440887, 0.022194935961012286, 0.024339147126000805, 0.026374505414839208, 0.0282869107887712, 0.030052581128092695, 0.03164675137143993, 0.033050413419978504, 0.034255099704226064, 0.03526241266015668, 0.0360769896228887, 0.03669860449845609, 0.037120549269832576, 0.03733422875193504, 0.037361073762679026};

inline double rescale_error(double delta, double absolute, double deviation) {
    double error = std::abs(delta);
    if (deviation != 0 && error != 0)
        error = deviation * std::min(1.0, std::pow(200.0 * error / deviation, 1.5));
    return std::max(error, 50.0 * eps * absolute);
}

template<class Function>
double qng(Function&& function, double left, double right) {
    if (left == right) return 0;
    const double half = (right - left) * 0.5, center = (right + left) * 0.5;
    const double middle = function(center);
    std::array<std::array<double, 2>, 10> samples{};
    std::array<double, 21> pairs{};
    double low = 0, estimate = w21b[5] * middle, absolute = w21b[5] * std::abs(middle);
    for (int group = 0; group != 2; ++group) {
        for (int i = 0; i != 5; ++i) {
            double point = group == 0 ? x1[i] : x2[i];
            double weight = group == 0 ? w21a[i] : w21b[i];
            double upper = function(center + half * point), lower = function(center - half * point);
            double pair = upper + lower;
            if (group == 0) low += w10[i] * pair;
            estimate += weight * pair;
            absolute += weight * (std::abs(upper) + std::abs(lower));
            samples[group * 5 + i] = {upper, lower};
            pairs[group * 5 + i] = pair;
        }
    }
    absolute *= half;
    double mean = estimate * 0.5, deviation = w21b[5] * std::abs(middle - mean);
    for (int i = 0; i != 5; ++i)
        deviation += w21a[i] * (std::abs(samples[i][0] - mean) + std::abs(samples[i][1] - mean))
                   + w21b[i] * (std::abs(samples[i + 5][0] - mean) + std::abs(samples[i + 5][1] - mean));
    // The first stopping check intentionally precedes deviation rescaling.
    double error = rescale_error((estimate - low) * half, absolute, deviation);
    deviation *= half;
    if (error < 1e-10 || error < 1e-10 * std::abs(estimate * half)) return estimate * half;
    double previous = estimate;
    estimate = w43b[11] * middle;
    for (int i = 0; i != 10; ++i) estimate += w43a[i] * pairs[i];
    for (int i = 0; i != 11; ++i) {
        double pair = function(center + half * x3[i]) + function(center - half * x3[i]);
        estimate += w43b[i] * pair;
        pairs[i + 10] = pair;
    }
    error = rescale_error((estimate - previous) * half, absolute, deviation);
    if (error < 1e-10 || error < 1e-10 * std::abs(estimate * half)) return estimate * half;
    estimate = w87b[22] * middle;
    for (int i = 0; i != 21; ++i) estimate += w87a[i] * pairs[i];
    for (int i = 0; i != 22; ++i)
        estimate += w87b[i] * (function(center + half * x4[i]) + function(center - half * x4[i]));
    return estimate * half;
}

inline double normal_cdf(double z) {
    double probability = 0.5 * (1 + std::erf(z * 0.7071067811865476));
    if (probability > 1e-8) return probability;
    const double square = z * z;
    if (!std::isfinite(square)) return 0;
    double series = 1, product = 1, previous = std::numeric_limits<double>::infinity();
    for (int order = 1; ; ++order) {
        double odd = (4.0 * order - 3) / square;
        double multiplier = odd * ((4.0 * order - 1) / square);
        double correction = product * (odd - multiplier);
        series -= correction;
        product *= multiplier;
        double magnitude = std::abs(correction);
        if (!(previous > magnitude && magnitude >= std::abs(series * eps))) break;
        previous = magnitude;
    }
    double density = -0.5 * z * z <= -690 ? 0 : phi_scale * std::exp(-0.5 * z * z);
    return -density / z * series;
}

inline double rank_integrand(const std::vector<double>& prizes, const std::vector<double>& stacks,
                             std::size_t hero, double t) {
    std::vector<double> probability(stacks.size(), 0);
    probability.back() = 1;
    const double log_t = std::log(t);
    std::size_t processed = 0;
    for (std::size_t player = 0; player != stacks.size(); ++player) {
        if (player == hero) continue;
        double behind = std::exp(log_t * stacks[player] / stacks[hero]);
        for (std::size_t rank = stacks.size() - 2 - processed; rank + 1 < stacks.size(); ++rank) {
            double transfer = probability[rank + 1] * behind;
            probability[rank] += transfer;
            probability[rank + 1] -= transfer;
        }
        ++processed;
    }
    double result = 0;
    for (std::size_t rank = 0; rank != std::min(prizes.size(), stacks.size()); ++rank) result += prizes[rank] * probability[rank];
    return result;
}

inline double edgeworth_integrand(const std::vector<double>& prizes, const std::vector<double>& stacks,
                                  std::size_t hero, double t) {
    const double log_t = std::log(t);
    double mean = 0, variance = 0, third = 0;
    for (std::size_t player = 0; player != stacks.size(); ++player) {
        if (player == hero) continue;
        double q = std::exp(log_t * stacks[player] / stacks[hero]);
        double v = q * (1 - q);
        mean += q;
        variance += v;
        third += v * (1 - 2 * q);
    }
    if (variance <= 0) return rank_integrand(prizes, stacks, hero, t);
    double sigma = std::sqrt(variance), skewness = third * std::pow(sigma, -3.0);
    auto cumulative = [&](double behind) {
        double z = (behind + 0.5 - mean) / sigma;
        double density = -0.5 * z * z <= -690 ? 0 : phi_scale * std::exp(-0.5 * z * z);
        return normal_cdf(z) + skewness * (1 - z * z) * density / 6;
    };
    double previous = cumulative(static_cast<double>(stacks.size()) - 1), value = 0;
    for (std::size_t rank = 0; rank != prizes.size(); ++rank) {
        if (rank + 1 == prizes.size() || prizes[rank] != prizes[rank + 1]) {
            double current = cumulative(static_cast<double>(stacks.size()) - rank - 2);
            value += prizes[rank] * (previous - current);
            previous = current;
        }
    }
    return std::isnan(value) ? rank_integrand(prizes, stacks, hero, t) : value;
}

inline void validate(const std::vector<double>& data, bool positive) {
    for (double x : data)
        if (!std::isfinite(x) || (positive ? x <= 0 : x < 0))
            throw std::invalid_argument("MTT inputs require finite positive stacks / nonnegative payouts");
}

inline double compensated_sum(const std::vector<double>& data) {
    double sum = 0, correction = 0;
    for (double x : data) {
        double adjusted = x - correction, next = sum + adjusted;
        correction = (next - sum) - adjusted;
        sum = next;
    }
    return sum - correction;
}
} // namespace detail

class Calculator {
    const std::vector<double> payouts_, other_;
public:
    Calculator(std::vector<double> payouts, std::vector<double> other_stacks = {})
        : payouts_(std::move(payouts)), other_(std::move(other_stacks)) {
        detail::validate(payouts_, false);
        detail::validate(other_, true);
        if (payouts_.empty()) throw std::invalid_argument("MTT payouts must not be empty");
        for (std::size_t i = 1; i != payouts_.size(); ++i)
            if (payouts_[i] > payouts_[i - 1]) throw std::invalid_argument("MTT payouts must be descending");
    }
    bool approximate() const noexcept { return other_.size() >= 100; }
    std::vector<double> equities(const std::vector<double>& table_stacks) const {
        detail::validate(table_stacks, true);
        if (table_stacks.empty()) throw std::invalid_argument("MTT needs a surviving table player");
        std::vector<double> field = table_stacks;
        field.insert(field.end(), other_.begin(), other_.end());
        double total = detail::compensated_sum(field);
        if (!std::isfinite(total) || (field.size() > 1 && total <= *std::max_element(field.begin(), field.end())))
            throw std::invalid_argument("MTT field ratios exceed stable float64 domain");
        std::vector<double> tail = payouts_, output;
        tail[0] = 0;
        if (tail.size() > 1) tail[1] = 0;
        bool has_tail = std::any_of(tail.begin(), tail.end(), [](double p) { return p != 0; });
        output.reserve(table_stacks.size());
        for (std::size_t hero = 0; hero != table_stacks.size(); ++hero) {
            double value = 0;
            if (has_tail) {
                auto approx = [&](double t) { return detail::edgeworth_integrand(tail, field, hero, t); };
                auto integrand = [&](double t) { return approximate() ? approx(t) : detail::rank_integrand(tail, field, hero, t); };
                double left = 0;
                for (int segment = 0; segment != 20; ++segment) {
                    if (approx((1 - left) * 0.75) != 0 || value != 0) break;
                    double right = left + (1 - left) * 0.75;
                    value += detail::qng(integrand, left, right);
                    left = right;
                }
                value += detail::qng(integrand, left, 1);
            }
            value += field[hero] / total * payouts_[0];
            if (payouts_.size() > 1) {
                double second = 0;
                for (std::size_t player = 0; player != field.size(); ++player)
                    if (player != hero) second += field[player] / total * field[hero] / (total - field[player]);
                value += payouts_[1] * second;
            }
            if (!std::isfinite(value)) throw std::runtime_error("Nonfinite MTT approximate equity");
            output.push_back(value);
        }
        return output;
    }
    std::vector<double> operator()(const std::vector<double>& table_stacks) const { return equities(table_stacks); }
};

inline std::vector<double> equities(const std::vector<double>& table_stacks, const std::vector<double>& payouts,
                                    const std::vector<double>& other_stacks = {}) {
    return Calculator(payouts, other_stacks).equities(table_stacks);
}
} // namespace hrc_mtt
